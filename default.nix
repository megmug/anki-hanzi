{
  system ? builtins.currentSystem,
  cudaTorchVersion ? "2.12.0",
  cudaTorchIndexUrl ? "https://download.pytorch.org/whl/cu130",
  buildId ? null,
  writeDiagnosticDatabases ? false,
  pkgs ? import (builtins.fetchGit {
    url = "https://github.com/nixos/nixpkgs/";
    ref = "nixos-26.05";
    rev = "78e9c786dc08cd4f3420c2395cd977206a9b1da2";
  }) { inherit system; },
}:

let
  gitHeadPath = ./.git/HEAD;
  gitHead =
    if builtins.pathExists gitHeadPath then pkgs.lib.trim (builtins.readFile gitHeadPath) else "";
  gitHeadRef =
    if pkgs.lib.hasPrefix "ref: " gitHead then pkgs.lib.removePrefix "ref: " gitHead else "";
  gitHeadRefPath = ./.git + "/${gitHeadRef}";
  gitCommit =
    if buildId != null then
      buildId
    else if gitHeadRef != "" && builtins.pathExists gitHeadRefPath then
      pkgs.lib.trim (builtins.readFile gitHeadRefPath)
    else if gitHead != "" && !(pkgs.lib.hasPrefix "ref: " gitHead) then
      gitHead
    else
      "unknown";
  resolvedBuildId = if gitCommit == "unknown" then "unknown" else builtins.substring 0 7 gitCommit;
  deckConfigPath = ./deck_inputs/deck_config.json;
  deckConfig =
    if builtins.pathExists deckConfigPath then
      builtins.fromJSON (builtins.readFile deckConfigPath)
    else
      { };
  deckAudioConfig = deckConfig.audio or { };
  deckAudioEngine =
    if builtins.isAttrs deckAudioConfig then deckAudioConfig.engine or "off" else "off";
  rawNormalizedDeckAudioEngine = pkgs.lib.toLower (
    pkgs.lib.replaceStrings [ "-" ] [ "_" ] (toString deckAudioEngine)
  );
  supportedAudioEngines = [
    "off"
    "kokoro"
    "edge_tts"
  ];
  normalizedDeckAudioEngine =
    if builtins.elem rawNormalizedDeckAudioEngine supportedAudioEngines then
      rawNormalizedDeckAudioEngine
    else
      builtins.throw "deck_inputs/deck_config.json audio.engine must be one of: off, kokoro, edge_tts";
  needsKokoroAudio = normalizedDeckAudioEngine == "kokoro";
  needsEdgeTtsAudio = normalizedDeckAudioEngine == "edge_tts";
  needsAudioBuild = needsKokoroAudio || needsEdgeTtsAudio;
  needsNetworkBuild = needsAudioBuild;

  enableCudaPip = needsKokoroAudio && pkgs.stdenv.isLinux;
  kokoroAudioSupported =
    if needsKokoroAudio && pkgs.stdenv.isDarwin then
      builtins.throw "audio.engine=kokoro is not supported by this Nix build on Darwin because nixpkgs kokoro depends on Darwin-broken dlinfo via phonemizer. Use audio.engine=off or edge_tts on macOS."
    else
      true;

  pythonBase = pkgs.python313;
  pythonPackages = pythonBase.pkgs;

  colorize-pinyin = pythonPackages.buildPythonPackage rec {
    pname = "colorize-pinyin";
    version = "2.1.1";
    format = "setuptools";

    src = pkgs.fetchPypi {
      pname = "colorize_pinyin";
      inherit version;
      hash = "sha256-0qqa2uUOqaLVkEJxDugwtQIKF8Ba5cRVeGww4oS+j7k=";
    };

    doCheck = false;
  };

  pinyin-tone-converter = pythonPackages.buildPythonPackage rec {
    pname = "pinyin-tone-converter";
    version = "1.0.2";
    format = "setuptools";

    src = pkgs.fetchPypi {
      pname = "pinyin-tone-converter";
      inherit version;
      hash = "sha256-f0qq9EUT83Y4HMUzaK+rIDij8UEuLQqx2VwwKvWAJ9w=";
    };

    doCheck = false;
  };

  proces = pythonPackages.buildPythonPackage rec {
    pname = "proces";
    version = "0.1.7";
    format = "setuptools";

    src = pkgs.fetchPypi {
      inherit pname version;
      hash = "sha256-cKBdnpc91oX3qQksWL5pWoGBpBHWN5bCEyMv0/3EN3U=";
    };

    doCheck = false;
  };

  cn2an = pythonPackages.buildPythonPackage rec {
    pname = "cn2an";
    version = "0.5.24";
    format = "setuptools";

    src = pkgs.fetchPypi {
      inherit pname version;
      hash = "sha256-wnbPxLPJ51ghSEHeWXUC6xeN5QuNomM+00VWT5BwXw4=";
    };

    propagatedBuildInputs = [
      proces
    ];

    doCheck = false;
  };

  pypinyin-dict = pythonPackages.buildPythonPackage rec {
    pname = "pypinyin-dict";
    version = "0.9.0";
    format = "setuptools";

    src = pkgs.fetchPypi {
      pname = "pypinyin_dict";
      inherit version;
      hash = "sha256-jEkTlrqhVnMR8ux1nLwVRjjzvO/ccR005T43PjpCn6U=";
    };

    propagatedBuildInputs = with pythonPackages; [
      pypinyin
    ];

    doCheck = false;
  };

  pythonEnv =
    assert kokoroAudioSupported;
    pythonBase.withPackages (
      ps:
      with ps;
      [
        colorize-pinyin
        pinyin-tone-converter
        cn2an
        dragonmapper
        genanki
        pip
        setuptools
        wheel
      ]
      ++ pkgs.lib.optionals needsEdgeTtsAudio [
        edge-tts
      ]
      ++ pkgs.lib.optionals needsKokoroAudio (
        [
          # Core deps already present in nixpkgs that Kokoro reuses
          torch
          numpy
          scipy
          soundfile
          kokoro
          pypinyin-dict
        ]
        ++ misaki.optional-dependencies.zh
      )
    );

  yarnOfflineCache = pkgs.fetchYarnDeps {
    yarnLock = ./yarn.lock;
    hash = "sha256-wasqEk25KjOyWe8b8FN5OFqFhqE41UD6+6w+0Qxmkvc=";
  };

  materialSymbolsRev = "5d5d1fdd5476f3df3749e9fb872e32021ec7a750";
  materialSymbolsOutlinedFont = pkgs.fetchurl {
    name = "MaterialSymbolsOutlined.woff2";
    url = "https://raw.githubusercontent.com/google/material-design-icons/${materialSymbolsRev}/variablefont/MaterialSymbolsOutlined%5BFILL%2CGRAD%2Copsz%2Cwght%5D.woff2";
    sha256 = "0xy6dnrf1ijkipcfc5lnz87zfjcj2m8m2dmvgb328hakngq3yzjd";
  };

  root = toString ./.;
  relPath =
    path:
    let
      pathString = toString path;
    in
    if pathString == root then "" else pkgs.lib.removePrefix (root + "/") pathString;

  localBuildSource = pkgs.lib.cleanSourceWith {
    name = "anki-hanzi-local-build-source";
    src = ./.;
    filter =
      path: type:
      let
        rel = relPath path;
        base = baseNameOf path;
        pathSegments = pkgs.lib.splitString "/" rel;
        isUnderRootDir = dir: rel == dir || pkgs.lib.hasPrefix (dir + "/") rel;
        hasPathSegment = segment: builtins.elem segment pathSegments;
        excludedRootDirs = [
          ".agents"
          ".backup"
          ".codex"
          ".config"
          ".git"
          ".npm-cache"
          ".yarn-cache"
          "build_reports"
          "ci-artifacts"
          "master_db_output"
          "node_modules"
          "result"
        ];
        excludedDirNames = [
          ".pytest-cache"
          ".pytest_cache"
          "__pycache__"
        ];
        isGeneratedFile =
          base == ".DS_Store"
          || base == ".backup"
          || base == ".config"
          || base == ".env.local"
          || pkgs.lib.hasPrefix ".env." base
          || pkgs.lib.hasSuffix ".apkg" base
          || pkgs.lib.hasSuffix "_report.json" base
          || pkgs.lib.hasSuffix "_comparison.json" base;
      in
      !(pkgs.lib.any isUnderRootDir excludedRootDirs)
      && !(pkgs.lib.any hasPathSegment excludedDirNames)
      && !(type != "directory" && isGeneratedFile);
  };
  gitMetadataSource = pkgs.lib.cleanSourceWith {
    name = "anki-hanzi-git-metadata";
    src = ./.;
    filter =
      path: type:
      let
        rel = relPath path;
      in
      (type == "directory" || type == "regular" || type == "symlink")
      && (
        rel == ""
        || rel == ".git"
        || rel == ".git/HEAD"
        || rel == ".git/packed-refs"
        || rel == ".git/refs"
        || pkgs.lib.hasPrefix ".git/refs/" rel
        || rel == ".git/objects"
        || pkgs.lib.hasPrefix ".git/objects/" rel
      );
  };
  knownBuildIdsFile =
    pkgs.runCommandLocal "anki-hanzi-known-build-ids"
      {
        nativeBuildInputs = [ pkgs.git ];
        src = gitMetadataSource;
      }
      ''
        if git -c safe.directory="$src" -C "$src" rev-parse --git-dir >/dev/null 2>&1; then
          if ! git -c safe.directory="$src" -C "$src" rev-list --first-parent --reverse --abbrev-commit --abbrev=7 "${gitCommit}" > "$out"; then
            printf '%s\n' "${resolvedBuildId}" > "$out"
          fi
        else
          printf '%s\n' "${resolvedBuildId}" > "$out"
        fi
      '';

  hanzi-apkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "anki-hanzi-custom-apkg";
    version = "2025-local";
    src = localBuildSource;
    inherit yarnOfflineCache;

    nativeBuildInputs = with pkgs; [
      nodejs_26
      yarnConfigHook
      pythonEnv
      pkg-config
      gnumake
      espeak-ng
      ffmpeg
      nixfmt
      prettier
      ruff
      treefmt
    ];

    # Allow network access during audio builds so Kokoro can download
    # HuggingFace model weights.
    # NOTE: Requires sandbox = false or relaxed in nix.conf when network is used.
    __noChroot = needsNetworkBuild;

    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';

    shellHook = ''
      export YARN_CACHE_FOLDER="$PWD/.yarn-cache"
      export npm_config_cache="$PWD/.npm-cache"
    '';

    buildPhase = ''
            runHook preBuild

            export HOME="$TMPDIR/home"
            mkdir -p "$HOME"

            # huggingface_hub/httpx needs CA certs for HTTPS downloads
            export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
            export ANKI_HANZI_BUILD_ID="${resolvedBuildId}"
            export ANKI_HANZI_KNOWN_BUILD_IDS="$(cat ${knownBuildIdsFile})"
            AUDIO_ENGINE="${normalizedDeckAudioEngine}"
            echo "=== deck audio engine: $AUDIO_ENGINE ==="
            echo "=== pip CUDA PyTorch: ${if enableCudaPip then "auto/probe" else "disabled"} ==="
            echo "=== material symbols: google/material-design-icons ${materialSymbolsRev} ==="

            install -Dm644 ${materialSymbolsOutlinedFont} \
              tooling/lib/anki_hanzi/deck/template_resources/fonts/_MaterialSymbolsOutlined.woff2

            # Isolate the optional CUDA PyTorch wheel so it does not clash with Nix python.
            PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
            CUDA_PIP_PREFIX="$TMPDIR/cuda-pip"
            SITE_PACKAGES="$CUDA_PIP_PREFIX/lib/python''${PYTHON_VERSION}/site-packages"
            export PYTHONPATH="$SITE_PACKAGES:$PYTHONPATH"
            export PATH="$CUDA_PIP_PREFIX/bin:$PATH"
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            mkdir -p "$CUDA_PIP_PREFIX"

            ${pkgs.lib.optionalString enableCudaPip ''
                    CUDA_DRIVER_LIB_DIR="$TMPDIR/nvidia-driver-libs"
                    mkdir -p "$CUDA_DRIVER_LIB_DIR"
                    CUDA_DRIVER_FOUND=0
                    for driver_lib in \
                      /run/opengl-driver/lib \
                      /usr/lib/x86_64-linux-gnu \
                      /usr/lib64 \
                      /usr/lib/wsl/lib; do
                      if [ -d "$driver_lib" ]; then
                        while IFS= read -r lib; do
                          resolved="$(readlink -f "$lib" || true)"
                          if [ -n "$resolved" ]; then
                            ln -sf "$resolved" "$CUDA_DRIVER_LIB_DIR/$(basename "$lib")"
                          fi
                        done < <(find "$driver_lib" -maxdepth 1 \( -type f -o -type l \) \( \
                          -name 'libcuda.so*' -o \
                          -name 'libnvidia-*.so*' \
                        \))
                      fi
                    done

                    if find "$CUDA_DRIVER_LIB_DIR" -maxdepth 1 -name 'libcuda.so*' -print -quit | grep -q .; then
                      CUDA_DRIVER_FOUND=1
                    elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
                      CUDA_DRIVER_FOUND=1
                    fi

                    if [ "$CUDA_DRIVER_FOUND" != "1" ]; then
                      echo "=== No NVIDIA CUDA driver detected; using Nix CPU PyTorch ==="
                    else
                      echo "=== Installing CUDA-enabled PyTorch wheel into isolated pip prefix ==="
                      if ! pip install --prefix "$CUDA_PIP_PREFIX" --no-cache-dir \
                        --ignore-installed --force-reinstall \
                        --index-url "${cudaTorchIndexUrl}" \
                        "torch==${cudaTorchVersion}"; then
                        echo "WARNING: CUDA PyTorch wheel installation failed; falling back to Nix CPU PyTorch"
                        rm -rf "$CUDA_PIP_PREFIX"
                        mkdir -p "$CUDA_PIP_PREFIX"
                      else
                        export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$CUDA_DRIVER_LIB_DIR''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
                        if ! python - <<'PY'; then
              import ctypes.util
              import sys
              import torch

              print(
                  "=== PyTorch",
                  torch.__version__,
                  "from",
                  torch.__file__,
                  "CUDA",
                  torch.version.cuda,
                  "available",
                  torch.cuda.is_available(),
                  "devices",
                  torch.cuda.device_count(),
                  "libcuda",
                  ctypes.util.find_library("cuda"),
                  "===",
              )
              if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
                  sys.exit(1)
              PY
                          echo "WARNING: CUDA PyTorch import/probe failed; falling back to Nix CPU PyTorch"
                          rm -rf "$CUDA_PIP_PREFIX"
                          mkdir -p "$CUDA_PIP_PREFIX"
                          export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib"
                        fi
                      fi
                    fi
            ''}

            # Audio dependencies are included in the Nix python env only for the
            # configured audio engine.
            if [ "$AUDIO_ENGINE" = "kokoro" ]; then
              if ! python -c "import kokoro" 2>/dev/null; then
                echo "ERROR: Kokoro import failed in Nix python environment"
                exit 1
              fi
              if ! python - <<'PY' 2>/dev/null; then
      from kokoro import KPipeline
      KPipeline(lang_code="z")
      PY
                echo "ERROR: Kokoro Chinese pipeline failed in Nix python environment"
                exit 1
              fi
              echo "=== Kokoro Chinese pipeline available ==="
            fi
            if [ "$AUDIO_ENGINE" = "edge_tts" ]; then
              if ! python -c "import edge_tts" 2>/dev/null; then
                echo "ERROR: edge-tts import failed in Nix python environment"
                exit 1
              fi
              echo "=== edge-tts available ==="
            fi

            # Nix source paths use normalized mtimes that can predate ZIP's 1980
            # lower bound. Use the generator's fixed ZIP timestamp for all media
            # files materialized in this store build.
            find . -type f -exec touch -t 202605200639.48 {} +

            diagnosticDatabaseArgs=()
            if [ "${if writeDiagnosticDatabases then "1" else "0"}" = "1" ]; then
              diagnosticDatabaseArgs+=(
                --master-db-output master_db_output/cc_cedict_master.json
                --enriched-db-output master_db_output/cc_cedict_hanzi_enriched.json
              )
            fi

            python tooling/build/generate_hanzi_deck.py \
              --timestamp 1779251987.6 \
              --zip-generated-datetime 2026-05-20T06:39:48 \
              "''${diagnosticDatabaseArgs[@]}"

            runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out"
      cp "anki-hanzi.apkg" "$out/anki-hanzi-${resolvedBuildId}.apkg"
      cp "anki-hanzi-migrator.ankiaddon" "$out/anki-hanzi-migrator-${resolvedBuildId}.ankiaddon"
      cp build_reports/build_report.json "$out/"
      if [ -d master_db_output ]; then
        mkdir -p "$out/diagnostics"
        find master_db_output -maxdepth 1 -type f -name '*.json' -exec cp {} "$out/diagnostics/" \;
      fi
      runHook postInstall
    '';
  };
in

hanzi-apkg
