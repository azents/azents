# SendCodeResponse

Authentication code send response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**csrf_token** | **str** | CSRF token (used on verification) | 

## Example

```python
from azentspublicclient.models.send_code_response import SendCodeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SendCodeResponse from a JSON string
send_code_response_instance = SendCodeResponse.from_json(json)
# print the JSON string representation of the object
print(SendCodeResponse.to_json())

# convert the object into a dict
send_code_response_dict = send_code_response_instance.to_dict()
# create an instance of SendCodeResponse from a dict
send_code_response_from_dict = SendCodeResponse.from_dict(send_code_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


