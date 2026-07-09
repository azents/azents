# BootstrapFirstOwnerResponse

First owner bootstrap response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_handle** | **str** | Created Workspace handle | 
**user_id** | **str** | Created Owner User ID | 

## Example

```python
from azentsadminclient.models.bootstrap_first_owner_response import BootstrapFirstOwnerResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BootstrapFirstOwnerResponse from a JSON string
bootstrap_first_owner_response_instance = BootstrapFirstOwnerResponse.from_json(json)
# print the JSON string representation of the object
print(BootstrapFirstOwnerResponse.to_json())

# convert the object into a dict
bootstrap_first_owner_response_dict = bootstrap_first_owner_response_instance.to_dict()
# create an instance of BootstrapFirstOwnerResponse from a dict
bootstrap_first_owner_response_from_dict = BootstrapFirstOwnerResponse.from_dict(bootstrap_first_owner_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


