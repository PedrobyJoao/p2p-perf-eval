{
  description = "Nim project flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self
    , nixpkgs
    , flake-utils
    , ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            nim
            nimble
            nimlangserver
          ];

          # so when you run `nix develop` your ~/.nimble/bin
          # is also in PATH, for per-user nimble installs:
          shellHook = ''
            export PATH=$HOME/.nimble/bin:$PATH
          '';
        };
      }
    );
}
