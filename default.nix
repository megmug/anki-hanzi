{ pkgs ? import ( builtins.fetchGit {
    url = "https://github.com/nixos/nixpkgs/";
    ref = "nixos-25.11";
    rev = "d7a713c0b7e47c908258e71cba7a2d77cc8d71d5";
} ) {}
, enforceApkgHash ? true
}:

let
  apkgHashMode = if enforceApkgHash then "enforce" else "record";

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
    hash = "sha256-fWhXM2cU1MwofvZTNq3SHwRsdbbkP5KdeARewXML6Xo=";
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
          "_complete-hsk-vocabulary"
          "anki-xie-hanzi-2.2.1-to-2.3-migrator"
          "build"
          "build_reports"
          "complete-hsk-vocabulary"
          "node_modules"
          "source_comparison_output"
        ];
        isMasterDbGenerated = pkgs.lib.hasPrefix "master_db_output/" rel;
        isGeneratedFile =
          base == ".DS_Store"
          || rel == "result"
          || pkgs.lib.hasSuffix ".apkg" base
          || pkgs.lib.hasSuffix "_report.json" base
          || pkgs.lib.hasSuffix "_hash_verification.json" base
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

      python scripts/build_cc_cedict_master_db.py
      python scripts/enrich_xiehanzi_db.py

      # Nix source paths use normalized mtimes that can predate ZIP's 1980
      # lower bound. Use the generator's fixed ZIP timestamp for all media
      # files materialized in this transitional store build.
      find . -type f -exec touch -t 202605200639.48 {} +

      python scripts/generate_xiehanzi_deck.py \
        --timestamp 1779251987.6 \
        --zip-generated-datetime 2026-05-20T06:39:48
      python scripts/verify_apkg_hash.py \
        --apkg "Anki-xiehanzi - New HSK (2025).apkg" \
        --pin deck_inputs/apkg_build_invariant.json \
        --output build_reports/generate_xiehanzi_hash_verification.json \
        --mode ${apkgHashMode}

      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall

      mkdir -p "$out"
      cp "Anki-xiehanzi - New HSK (2025).apkg" "$out/"
      cp build_reports/generate_xiehanzi_report.json "$out/"
      cp build_reports/generate_xiehanzi_hash_verification.json "$out/"
      cp master_db_output/cc_cedict_xiehanzi_enriched.json "$out/"
      cp master_db_output/xiehanzi_enrichment_report.json "$out/"

      runHook postInstall
    '';
  };
in

xiehanzi-apkg
