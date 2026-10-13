# GitHubSetupConnectivity


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_setup_connectivity import GitHubSetupConnectivity

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubSetupConnectivity from a JSON string
git_hub_setup_connectivity_instance = GitHubSetupConnectivity.from_json(json)
# print the JSON string representation of the object
print(GitHubSetupConnectivity.to_json())

# convert the object into a dict
git_hub_setup_connectivity_dict = git_hub_setup_connectivity_instance.to_dict()
# create an instance of GitHubSetupConnectivity from a dict
git_hub_setup_connectivity_from_dict = GitHubSetupConnectivity.from_dict(git_hub_setup_connectivity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


