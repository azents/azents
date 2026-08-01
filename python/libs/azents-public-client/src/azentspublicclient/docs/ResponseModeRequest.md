# ResponseModeRequest

Required full-value response-mode request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**response_mode** | [**ExternalChannelResponseMode**](ExternalChannelResponseMode.md) |  | 

## Example

```python
from azentspublicclient.models.response_mode_request import ResponseModeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ResponseModeRequest from a JSON string
response_mode_request_instance = ResponseModeRequest.from_json(json)
# print the JSON string representation of the object
print(ResponseModeRequest.to_json())

# convert the object into a dict
response_mode_request_dict = response_mode_request_instance.to_dict()
# create an instance of ResponseModeRequest from a dict
response_mode_request_from_dict = ResponseModeRequest.from_dict(response_mode_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


