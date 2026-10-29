# SupplyState


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supply_id** | **str** |  | 
**agent_id** | **str** |  | 
**subject** | **str** |  | 
**issuer** | **str** |  | 
**current_token_id** | **str** |  | 
**revoked_at** | **datetime** |  | 
**tokens** | [**List[TokenState]**](TokenState.md) |  | 

## Example

```python
from azentsadminclient.models.supply_state import SupplyState

# TODO update the JSON string below
json = "{}"
# create an instance of SupplyState from a JSON string
supply_state_instance = SupplyState.from_json(json)
# print the JSON string representation of the object
print(SupplyState.to_json())

# convert the object into a dict
supply_state_dict = supply_state_instance.to_dict()
# create an instance of SupplyState from a dict
supply_state_from_dict = SupplyState.from_dict(supply_state_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


