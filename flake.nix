{
  description = "A Python development environment with uv in an FHS shell.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self
    , nixpkgs
    , flake-utils
    ,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        fhs = pkgs.buildFHSEnv {
          name = "uv-fhs-env";
          targetPkgs =
            pkgs:
            (with pkgs; [
              uv

              # Essential build toolchain for compiling C extensions.
              gcc
              zlib
              openssl
              pkg-config

              # Crucial for making dynamically-linked binaries work.
              nix-ld
            ]);
          runScript = "bash";

          profile = ''
            export PATH="$HOME/.local/bin:$PATH"

            rm pyrightconfig.json
            echo '{ "venvPath": ".", "venv": ".venv" }' >> pyrightconfig.json

            uv venv
            uv sync
          '';

        };
      in
      {
        # This assigns the FHS environment's setup script directly to the devShell
        devShells.default = fhs.env;
      }
    );
}
