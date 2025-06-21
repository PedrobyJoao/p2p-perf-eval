{
  description = "poc p2p analysis";

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
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ ];
        };
      in
      {
        packages = rec {
          p2p-analysis = pkgs.buildGoModule {
            pname = "p2p-analysis";
            # inherit version;
            src = ./.;
            vendorHash = null; # Let nix compute the vendor hash

            buildInputs = with pkgs; [
              pkg-config
              sqlite
            ];

            # Add any necessary build flags here
            buildFlags = [
              "-tags=libsqlite3"
            ];

          };
          default = p2p-analysis;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            go
            gopls
            gotools
            go-tools
            sqlite
            pkg-config
            systemd.dev

            # dev tools
            zip
            gnumake
          ];

          shellHook = ''
            export CGO_ENABLED=1
            export PKG_CONFIG_PATH="${pkgs.systemd.dev}/lib/pkgconfig:$PKG_CONFIG_PATH"
            # solves: https://github.com/NVIDIA/nvidia-container-toolkit/issues/49
            export GOFLAGS="-ldflags=-extldflags=-Wl,-z,lazy"
          '';
        };
      }
    );
}
