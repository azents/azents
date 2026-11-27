# VaultRequestView

Value-free current request state, including immediate effective expiry.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**request_id** | **str** |  | 
**purpose** | **str** |  | 
**fields** | [**List[VaultRequestField]**](VaultRequestField.md) |  | 
**status** | [**VaultRequestStatus**](VaultRequestStatus.md) |  | 
**deadline_at** | **datetime** |  | 
**can_submit** | **bool** |  | 

## Example

```python
from azentspublicclient.models.vault_request_view import VaultRequestView

# TODO update the JSON string below
json = "{}"
# create an instance of VaultRequestView from a JSON string
vault_request_view_instance = VaultRequestView.from_json(json)
# print the JSON string representation of the object
print(VaultRequestView.to_json())

# convert the object into a dict
vault_request_view_dict = vault_request_view_instance.to_dict()
# create an instance of VaultRequestView from a dict
vault_request_view_from_dict = VaultRequestView.from_dict(vault_request_view_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


