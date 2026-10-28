# Third-party composition

The Azents extension is MIT-licensed. Its inference server is the original
LiteLLM Proxy from Berri AI, pinned to
`c7c895db456eda349a7be9661b4b21f578f9b589` (distribution version `1.109.0`).
LiteLLM's root notice identifies its non-Enterprise sources as MIT-licensed.
The wheel's original license and dependency notices remain installed in their
distribution metadata. This project does not change license checks or enable
premium functionality.

The final runtime image includes the installed core wheel, the Azents extension,
the shared contract, and their locked dependencies. The source checkout and build
toolchain are confined to build stages. Neither the `enterprise` source tree nor
`litellm-enterprise` distribution belongs in the final image. The composition
audit checks the installed inventory and original MIT notice and emits the
installed dependency inventory during the image build.

Dependencies retain their respective licenses; this notice does not relicense
them or certify legal suitability. The MIT assertion concerns the selected
LiteLLM core/extension, not every component of the operating-system image.
