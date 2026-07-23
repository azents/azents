# ManagedGrant


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**principal_id** | **str** |  | 
**principal_label** | **str** |  | 
**principal_provider_user_id** | **str** |  | 
**scope** | [**ExternalChannelAccessGrantScope**](ExternalChannelAccessGrantScope.md) |  | 
**agent_session_id** | **str** |  | 
**created_at** | **datetime** |  | 
**revoked_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_grant import ManagedGrant

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedGrant from a JSON string
managed_grant_instance = ManagedGrant.from_json(json)
# print the JSON string representation of the object
print(ManagedGrant.to_json())

# convert the object into a dict
managed_grant_dict = managed_grant_instance.to_dict()
# create an instance of ManagedGrant from a dict
managed_grant_from_dict = ManagedGrant.from_dict(managed_grant_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


