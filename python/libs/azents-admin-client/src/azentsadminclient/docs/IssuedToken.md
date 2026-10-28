# IssuedToken


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supply_id** | **str** |  | 
**token_id** | **str** |  | 
**agent_token** | **str** |  | 
**expires_at** | **datetime** |  | 
**predecessor_expires_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.issued_token import IssuedToken

# TODO update the JSON string below
json = "{}"
# create an instance of IssuedToken from a JSON string
issued_token_instance = IssuedToken.from_json(json)
# print the JSON string representation of the object
print(IssuedToken.to_json())

# convert the object into a dict
issued_token_dict = issued_token_instance.to_dict()
# create an instance of IssuedToken from a dict
issued_token_from_dict = IssuedToken.from_dict(issued_token_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


