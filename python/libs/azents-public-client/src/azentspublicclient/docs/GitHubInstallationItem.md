# GitHubInstallationItem

GitHub App installation item.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **int** | Installation ID |
**account_login** | **str** | Installed account/organization name |
**account_type** | **str** | Account type (User/Organization) |
**account_avatar_url** | **str** | Account avatar URL |

## Example

```python
from azentspublicclient.models.git_hub_installation_item import GitHubInstallationItem

# TODO update the JSON string below
json = "{}"
# create an instance of GitHubInstallationItem from a JSON string
git_hub_installation_item_instance = GitHubInstallationItem.from_json(json)
# print the JSON string representation of the object
print(GitHubInstallationItem.to_json())

# convert the object into a dict
git_hub_installation_item_dict = git_hub_installation_item_instance.to_dict()
# create an instance of GitHubInstallationItem from a dict
git_hub_installation_item_from_dict = GitHubInstallationItem.from_dict(git_hub_installation_item_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


