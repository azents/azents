export PIXI_HOME="$HOME/.pixi"
export PIXI_CACHE_DIR="$HOME/.cache/pixi"

if [ -z "${PIXI_BASE_PATH+x}" ]; then
    export PIXI_BASE_PATH="$PATH"
fi

case "$(uname -m)" in
    x86_64 | amd64)
        export PIXI_PLATFORM=linux-64
        ;;
    aarch64 | arm64)
        export PIXI_PLATFORM=linux-aarch64
        ;;
esac

case ":$PATH:" in
    *":$PIXI_HOME/bin:"*) ;;
    *) export PATH="$PIXI_HOME/bin:$PATH" ;;
esac
