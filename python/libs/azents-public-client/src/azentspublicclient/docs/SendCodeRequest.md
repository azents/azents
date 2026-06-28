# SendCodeRequest

Authentication code send request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Email address |

## Example

```python
from azentspublicclient.models.send_code_request import SendCodeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SendCodeRequest from a JSON string
send_code_request_instance = SendCodeRequest.from_json(json)
# print the JSON string representation of the object
print(SendCodeRequest.to_json())

# convert the object into a dict
send_code_request_dict = send_code_request_instance.to_dict()
# create an instance of SendCodeRequest from a dict
send_code_request_from_dict = SendCodeRequest.from_dict(send_code_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


