{ pkgs ? import ( builtins.fetchGit {
    url = "https://github.com/nixos/nixpkgs/";
    ref = "nixos-25.11";
    rev = "d7a713c0b7e47c908258e71cba7a2d77cc8d71d5";
} ) {} }:

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
in

pkgs.mkShell {
  packages = with pkgs; [
    nodejs_20
    yarn
    (python3.withPackages (pythonPackages: with pythonPackages; [
      ipykernel
      colorize-pinyin
      pinyin-tone-converter
      dragonmapper
      edge-tts
      genanki
    ]))
    pkg-config
    gnumake
  ];

  shellHook = ''
    export YARN_CACHE_FOLDER="$PWD/.yarn-cache"
    export npm_config_cache="$PWD/.npm-cache"
  '';
}
