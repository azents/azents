# BootstrapFirstOwnerRequest

First owner bootstrap request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Owner email | 
**password** | **str** | Owner initial password | 
**owner_name** | **str** | Owner display name | 
**workspace_name** | **str** | Workspace name | 
**workspace_handle** | **str** | Workspace handle | 
**locale** | **str** | Locale (BCP 47) | [optional] [default to 'ko-KR']

## Example

```python
from azentspublicclient.models.bootstrap_first_owner_request import BootstrapFirstOwnerRequest

# TODO update the JSON string below
json = "{}"
# create an instance of BootstrapFirstOwnerRequest from a JSON string
bootstrap_first_owner_request_instance = BootstrapFirstOwnerRequest.from_json(json)
# print the JSON string representation of the object
print(BootstrapFirstOwnerRequest.to_json())

# convert the object into a dict
bootstrap_first_owner_request_dict = bootstrap_first_owner_request_instance.to_dict()
# create an instance of BootstrapFirstOwnerRequest from a dict
bootstrap_first_owner_request_from_dict = BootstrapFirstOwnerRequest.from_dict(bootstrap_first_owner_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


