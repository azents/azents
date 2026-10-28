# TokenRotateRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**supply_id** | **str** |  | 
**expected_token_id** | **str** |  | 

## Example

```python
from azentsadminclient.models.token_rotate_request import TokenRotateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TokenRotateRequest from a JSON string
token_rotate_request_instance = TokenRotateRequest.from_json(json)
# print the JSON string representation of the object
print(TokenRotateRequest.to_json())

# convert the object into a dict
token_rotate_request_dict = token_rotate_request_instance.to_dict()
# create an instance of TokenRotateRequest from a dict
token_rotate_request_from_dict = TokenRotateRequest.from_dict(token_rotate_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


