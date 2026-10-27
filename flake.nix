{
  description = "Anki Hanzi deck build and development environment";

  inputs = {
    self.submodules = true;
    nixpkgs.url = "git+https://github.com/nixos/nixpkgs/?ref=nixos-26.05";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      buildRevision =
        self.rev or (nixpkgs.lib.removeSuffix "-dirty" (
          self.dirtyRev or (throw "Build from a Git checkout so the deck has a valid BuildID.")
        ));
      # Flakes omit .git. Only deck builds read local history; the devShell stays pure.
      checkoutRoot =
        let
          pwd = builtins.getEnv "PWD";
        in
        if pwd != "" && builtins.pathExists (pwd + "/.git/HEAD") then
          builtins.toPath pwd
        else
          throw "Run nix build --impure from the repository root to include the migrator's local Git history.";
      projects = forAllSystems (
        system:
        import ./nix/project.nix {
          pkgs = nixpkgs.legacyPackages.${system};
          inherit buildRevision checkoutRoot;
        }
      );
    in
    {
      packages = forAllSystems (system: {
        default = projects.${system}.package;
        with-diagnostics =
          (import ./nix/project.nix {
            pkgs = nixpkgs.legacyPackages.${system};
            inherit buildRevision checkoutRoot;
            writeDiagnosticDatabases = true;
          }).package;
      });
      devShells = forAllSystems (system: {
        default = projects.${system}.devShell;
      });
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
