# TokenState


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**token_id** | **str** |  | 
**issued_at** | **datetime** |  | 
**expires_at** | **datetime** |  | 
**handover_until** | **datetime** |  | 
**revoked_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.token_state import TokenState

# TODO update the JSON string below
json = "{}"
# create an instance of TokenState from a JSON string
token_state_instance = TokenState.from_json(json)
# print the JSON string representation of the object
print(TokenState.to_json())

# convert the object into a dict
token_state_dict = token_state_instance.to_dict()
# create an instance of TokenState from a dict
token_state_from_dict = TokenState.from_dict(token_state_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


