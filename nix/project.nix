{
  pkgs,
  buildRevision,
  checkoutRoot,
  writeDiagnosticDatabases ? false,
}:

let
  resolvedBuildId = builtins.substring 0 7 buildRevision;
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

  pythonEnv = pythonBase.withPackages (
    ps: with ps; [
      colorize-pinyin
      dragonmapper
      genanki
    ]
  );

  yarnOfflineCache = pkgs.fetchYarnDeps {
    yarnLock = ../yarn.lock;
    hash = "sha256-wasqEk25KjOyWe8b8FN5OFqFhqE41UD6+6w+0Qxmkvc=";
  };

  materialSymbolsRev = "5d5d1fdd5476f3df3749e9fb872e32021ec7a750";
  materialSymbolsOutlinedFont = pkgs.fetchurl {
    name = "MaterialSymbolsOutlined.woff2";
    url = "https://raw.githubusercontent.com/google/material-design-icons/${materialSymbolsRev}/variablefont/MaterialSymbolsOutlined%5BFILL%2CGRAD%2Copsz%2Cwght%5D.woff2";
    sha256 = "0xy6dnrf1ijkipcfc5lnz87zfjcj2m8m2dmvgb328hakngq3yzjd";
  };

  root = toString ../.;
  relPath =
    path:
    let
      pathString = toString path;
    in
    if pathString == root then "" else pkgs.lib.removePrefix (root + "/") pathString;

  localBuildSource = pkgs.lib.cleanSourceWith {
    name = "anki-hanzi-local-build-source";
    src = ../.;
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
          ".direnv"
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
    src = checkoutRoot;
    filter =
      path: type:
      let
        rel = pkgs.lib.removePrefix (toString checkoutRoot + "/") (toString path);
      in
      (type == "directory" || type == "regular" || type == "symlink")
      && (
        toString path == toString checkoutRoot
        || rel == ".git"
        || rel == ".git/HEAD"
        || rel == ".git/packed-refs"
        || rel == ".git/shallow"
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
        if [ -s "$src/.git/shallow" ]; then
          echo "The migrator requires the complete local Git history, not a shallow clone." >&2
          exit 1
        fi
        git -c safe.directory="$src" -C "$src" rev-list \
          --first-parent --reverse --abbrev-commit --abbrev=7 \
          "${buildRevision}" > "$out"
      '';

  buildTools = with pkgs; [
    nodejs_26
    pythonEnv
    nixfmt
    prettier
    ruff
    treefmt
  ];

  hanzi-apkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "anki-hanzi-custom-apkg";
    version = "2025-local";
    src = localBuildSource;
    inherit yarnOfflineCache;

    nativeBuildInputs = buildTools ++ [ pkgs.yarnConfigHook ];

    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';

    buildPhase = ''
      runHook preBuild

      export HOME="$TMPDIR/home"
      mkdir -p "$HOME"

      export ANKI_HANZI_BUILD_ID="${resolvedBuildId}"
      export ANKI_HANZI_KNOWN_BUILD_IDS="$(cat ${knownBuildIdsFile})"
      echo "=== material symbols: google/material-design-icons ${materialSymbolsRev} ==="

      install -Dm644 ${materialSymbolsOutlinedFont} \
        tooling/lib/anki_hanzi/deck/template_resources/fonts/_MaterialSymbolsOutlined.woff2

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

{
  package = hanzi-apkg;
  devShell = pkgs.mkShell {
    packages = buildTools ++ [
      pkgs.yarn
      pkgs.git
    ];
    shellHook = ''
      export YARN_CACHE_FOLDER="$PWD/.yarn-cache"
      export npm_config_cache="$PWD/.npm-cache"
    '';
  };
}
