# GitHubSetupTransport

Only supported MCP transport settings, without a provider URL override.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolsets** | **List[str]** |  | 
**timeout** | **float** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_transport import GitHubSetupTransport

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupTransport from a JSON string
git_hub_setup_transport_instance = GitHubSetupTransport.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupTransport.to_json())

# convert the object into a dict
git_hub_setup_transport_dict = git_hub_setup_transport_instance.to_dict()
# create an instance of GitHubSetupTransport from a dict
git_hub_setup_transport_from_dict = GitHubSetupTransport.from_dict(git_hub_setup_transport_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


