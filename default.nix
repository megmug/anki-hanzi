{ pkgs ? import ( builtins.fetchGit {
    url = "https://github.com/nixos/nixpkgs/";
    ref = "nixos-25.11";
    rev = "d7a713c0b7e47c908258e71cba7a2d77cc8d71d5";
} ) {}
}:

let
  colorize-pinyin = pkgs.python3Packages.buildPythonPackage rec {
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

  pinyin-tone-converter = pkgs.python3Packages.buildPythonPackage rec {
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

  pythonEnv = pkgs.python3.withPackages (pythonPackages: with pythonPackages; [
    ipykernel
    colorize-pinyin
    pinyin-tone-converter
    dragonmapper
    edge-tts
    genanki
  ]);

  yarnOfflineCache = pkgs.fetchYarnDeps {
    yarnLock = ./yarn.lock;
    hash = "sha256-Vw4clkczVEKsY9A3+QKTN0psBOhhaCQhteB+rjRdemI=";
  };

  build-xiehanzi-apkg = pkgs.writeShellApplication {
    name = "build-xiehanzi-apkg";
    runtimeInputs = with pkgs; [
      nodejs_20
      yarn
      pythonEnv
    ];
    text = ''
      if [[ ! -f custom_build_cc_cedict_master_db.py || ! -f custom_generate_xiehanzi_deck_from_enriched_db.py ]]; then
        echo "build-xiehanzi-apkg must be run from the Anki-xiehanzi repository root" >&2
        exit 2
      fi

      export YARN_CACHE_FOLDER="''${YARN_CACHE_FOLDER:-$PWD/.yarn-cache}"
      export npm_config_cache="''${npm_config_cache:-$PWD/.npm-cache}"

      yarn install --frozen-lockfile
      python custom_build_cc_cedict_master_db.py
      python custom_enrich_xiehanzi_db.py
      python custom_generate_xiehanzi_deck_from_enriched_db.py
    '';
  };

  root = toString ./.;
  relPath = path:
    let
      pathString = toString path;
    in
      if pathString == root then "" else pkgs.lib.removePrefix (root + "/") pathString;

  localBuildSource = pkgs.lib.cleanSourceWith {
    name = "anki-xiehanzi-local-build-source";
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
          "anki-xie-hanzi-2.2.1-to-2.3-migrator"
          "build"
          "complete-hsk-vocabulary"
          "node_modules"
          "source_comparison_output"
        ];
        isMasterDbGenerated =
          pkgs.lib.hasPrefix "master_db_output/" rel
          && rel != "master_db_output/sources"
          && rel != "master_db_output/sources/cedict_1_0_ts_utf-8_mdbg.zip";
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

  xiehanzi-apkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "anki-xiehanzi-custom-apkg";
    version = "2025-local";
    src = localBuildSource;
    inherit yarnOfflineCache;

    nativeBuildInputs = with pkgs; [
      nodejs_20
      yarnConfigHook
      pythonEnv
      build-xiehanzi-apkg
      pkg-config
      gnumake
    ];

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

      python custom_build_cc_cedict_master_db.py --no-download
      python custom_enrich_xiehanzi_db.py

      # Nix source paths use normalized mtimes that can predate ZIP's 1980
      # lower bound. Use the generator's fixed ZIP timestamp for all media
      # files materialized in this transitional store build.
      find . -type f -exec touch -t 202605200639.48 {} +

      python custom_generate_xiehanzi_deck.py \
        --timestamp 1779251987.6 \
        --zip-generated-datetime 2026-05-20T06:39:48
      python custom_generate_xiehanzi_deck_from_enriched_db.py
      python custom_verify_xiehanzi_apkg_build.py \
        --reference "Anki-xiehanzi - New HSK (2025).apkg" \
        --candidate "Anki-xiehanzi - New HSK (2025) from enriched.apkg" \
        --output custom_generate_xiehanzi_build_verification.json

      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out"
      cp "Anki-xiehanzi - New HSK (2025).apkg" "$out/"
      cp "Anki-xiehanzi - New HSK (2025) from enriched.apkg" "$out/"
      cp custom_generate_xiehanzi_report.json "$out/"
      cp custom_generate_xiehanzi_from_enriched_report.json "$out/"
      cp custom_generate_xiehanzi_build_verification.json "$out/"
      cp master_db_output/xiehanzi_enrichment_report.json "$out/"

      runHook postInstall
    '';
  };
in

xiehanzi-apkg
