# Third-party composition

The Azents extension is MIT-licensed. Its inference server is the original
LiteLLM Proxy from Berri AI, installed from the published PyPI wheel
`litellm==1.109.0.dev1`. The exact registry artifact hashes are in `uv.lock`.
This development release is a requester-approved one-time exception for ChatGPT
request-credential forwarding (upstream PR #41522). Replace it with a stable
release containing that fix after equivalent regression checks.

LiteLLM's original notice identifies its non-Enterprise sources as MIT-licensed.
The wheel's license and dependency notices remain installed in distribution
metadata. This project does not change license checks or enable premium features.

The runtime image contains the installed core wheel, independently authored Azents
extension, shared contract and locked dependencies. It does not build LiteLLM from
an upstream checkout or include a Rust build toolchain. Neither the `enterprise`
source tree nor `litellm-enterprise` distribution belongs in the runtime image.
The composition audit checks installed inventory, exact release identity, absent
Enterprise/premium configuration and the original MIT notice; image build emits
the installed dependency inventory.

Dependencies retain their respective licenses. This notice does not relicense
them or certify legal suitability. The MIT assertion concerns the selected
LiteLLM core/extension, not every operating-system or third-party component.
