{ system ? builtins.currentSystem
, enableCuda ? false
, cudaTorchVersion ? "2.9.1"
, cudaTorchIndexUrl ? "https://download.pytorch.org/whl/cu128"
, pkgs ? import ( builtins.fetchGit {
    url = "https://github.com/nixos/nixpkgs/";
    ref = "nixos-25.11";
    rev = "d7a713c0b7e47c908258e71cba7a2d77cc8d71d5";
} ) {
  inherit system;
}
}:

let
  enableCudaPip = enableCuda && pkgs.stdenv.isLinux;

  colorize-pinyin = pkgs.python312Packages.buildPythonPackage rec {
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

  pinyin-tone-converter = pkgs.python312Packages.buildPythonPackage rec {
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

  # Kokoro and its heavy transitive dependencies are not available in
  # nixpkgs. We install them via pip during the buildPhase into an
  # isolated prefix. Network access is required (__noChroot = true).
  pythonBase = pkgs.python312;

  pythonEnv = pythonBase.withPackages (ps: with ps; [
    ipykernel
    colorize-pinyin
    pinyin-tone-converter
    dragonmapper
    edge-tts
    genanki
    pip
    setuptools
    wheel
    # Core deps already present in nixpkgs that Kokoro reuses
    torch
    numpy
    scipy
    soundfile
  ]);

  yarnOfflineCache = pkgs.fetchYarnDeps {
    yarnLock = ./yarn.lock;
    hash = "sha256-wasqEk25KjOyWe8b8FN5OFqFhqE41UD6+6w+0Qxmkvc=";
  };

  root = toString ./.;
  relPath = path:
    let
      pathString = toString path;
    in
      if pathString == root then "" else pkgs.lib.removePrefix (root + "/") pathString;

  localBuildSource = pkgs.lib.cleanSourceWith {
    name = "anki-hanzi-local-build-source";
    src = ./.;
    filter = path: type:
      let
        rel = relPath path;
        base = baseNameOf path;
        isUnder = dir: rel == dir || pkgs.lib.hasPrefix (dir + "/") rel;
        excludedDirs = [
          ".git"
          ".docusaurus"
          ".npm-cache"
          ".yarn-cache"
          "_complete-hsk-vocabulary"
          "anki-xie-hanzi-2.2.1-to-2.3-migrator"
          "build"
          "build_reports"
          "complete-hsk-vocabulary"
          "node_modules"
          "source_comparison_output"
          "test"
        ];
        isMasterDbGenerated = pkgs.lib.hasPrefix "master_db_output/" rel;
        isGeneratedFile =
          base == ".DS_Store"
          || rel == "result"
          || pkgs.lib.hasSuffix ".apkg" base
          || pkgs.lib.hasSuffix "_report.json" base
          || pkgs.lib.hasSuffix "_comparison.json" base;
      in
        !(pkgs.lib.any isUnder excludedDirs)
        && !isMasterDbGenerated
        && !(type != "directory" && isGeneratedFile);
  };

  hanzi-apkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "anki-hanzi-custom-apkg";
    version = "2025-local";
    src = localBuildSource;
    inherit yarnOfflineCache;

    nativeBuildInputs = with pkgs; [
      nodejs_20
      yarnConfigHook
      pythonEnv
      pkg-config
      gnumake
      espeak-ng
      ffmpeg
    ];

    # Allow network access during build so pip can install Kokoro
    # and download HuggingFace model weights.
    # NOTE: Requires sandbox = false or relaxed in nix.conf
    __noChroot = true;

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
      echo "=== pip CUDA PyTorch: ${if enableCudaPip then "enabled" else "disabled"} ==="

      # Isolate pip-installed packages so they don't clash with Nix python
      PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
      PIP_PREFIX="$TMPDIR/kokoro-pip"
      SITE_PACKAGES="$PIP_PREFIX/lib/python''${PYTHON_VERSION}/site-packages"
      export PIP_PREFIX="$PIP_PREFIX"
      export PYTHONPATH="$SITE_PACKAGES:$PYTHONPATH"
      export PATH="$PIP_PREFIX/bin:$PATH"
      export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      mkdir -p "$PIP_PREFIX"

      ${pkgs.lib.optionalString enableCudaPip ''
      CUDA_DRIVER_LIB_DIR="$TMPDIR/nvidia-driver-libs"
      mkdir -p "$CUDA_DRIVER_LIB_DIR"
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

      echo "=== Installing CUDA-enabled PyTorch wheel into pip prefix ==="
      if ! pip install --prefix "$PIP_PREFIX" --no-cache-dir \
        --ignore-installed --force-reinstall \
        --index-url "${cudaTorchIndexUrl}" \
        "torch==${cudaTorchVersion}"; then
        echo "WARNING: CUDA PyTorch wheel installation failed; falling back to Nix CPU PyTorch"
        rm -rf "$PIP_PREFIX"
        mkdir -p "$PIP_PREFIX"
      else
        export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$CUDA_DRIVER_LIB_DIR''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        if ! python -c "import ctypes.util, torch; print('=== PyTorch', torch.__version__, 'from', torch.__file__, 'CUDA', torch.version.cuda, 'available', torch.cuda.is_available(), 'devices', torch.cuda.device_count(), 'libcuda', ctypes.util.find_library('cuda'), '===')"; then
          echo "WARNING: CUDA PyTorch import/probe failed; falling back to Nix CPU PyTorch"
          rm -rf "$PIP_PREFIX"
          mkdir -p "$PIP_PREFIX"
          export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib"
        fi
      fi
      ''}

      # Install Kokoro + Chinese G2P deps if not present
      if ! python -c "import kokoro" 2>/dev/null; then
        echo "=== Installing Kokoro and Chinese G2P dependencies ==="
        pip install --prefix "$PIP_PREFIX" --no-cache-dir \
          kokoro misaki[zh] ordered-set pypinyin cn2an jieba
        if ! python -c "import kokoro" 2>/dev/null; then
          echo "ERROR: Kokoro installation failed"
          exit 1
        fi
        echo "=== Kokoro installation complete ==="
      fi

      python scripts/build_cc_cedict_master_db.py
      python scripts/enrich_hanzi_db.py

      # Nix source paths use normalized mtimes that can predate ZIP's 1980
      # lower bound. Use the generator's fixed ZIP timestamp for all media
      # files materialized in this transitional store build.
      find . -type f -exec touch -t 202605200639.48 {} +

      python scripts/generate_hanzi_deck.py \
        --timestamp 1779251987.6 \
        --zip-generated-datetime 2026-05-20T06:39:48

      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out"
      cp "anki-hanzi.apkg" "$out/"
      cp build_reports/generate_hanzi_report.json "$out/"
      cp master_db_output/cc_cedict_hanzi_enriched.json "$out/"
      cp master_db_output/hanzi_enrichment_report.json "$out/"

      runHook postInstall
    '';
  };
in

  hanzi-apkg
