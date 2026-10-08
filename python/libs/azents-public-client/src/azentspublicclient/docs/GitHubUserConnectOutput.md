# GitHubUserConnectOutput

One setup URL and its local attempt identifier.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**authorization_url** | **str** |  | 
**install_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.git_hub_user_connect_output import GitHubUserConnectOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubUserConnectOutput from a JSON string
git_hub_user_connect_output_instance = GitHubUserConnectOutput.from_json(json)
# print the JSON string representation of the object
print(GitHubUserConnectOutput.to_json())

# convert the object into a dict
git_hub_user_connect_output_dict = git_hub_user_connect_output_instance.to_dict()
# create an instance of GitHubUserConnectOutput from a dict
git_hub_user_connect_output_from_dict = GitHubUserConnectOutput.from_dict(git_hub_user_connect_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


