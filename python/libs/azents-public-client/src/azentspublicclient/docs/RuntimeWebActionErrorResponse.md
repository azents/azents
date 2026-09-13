# RuntimeWebActionErrorResponse

FastAPI envelope for a bounded Runtime Web control error.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | [**RuntimeWebActionErrorDetail**](RuntimeWebActionErrorDetail.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_web_action_error_response import RuntimeWebActionErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebActionErrorResponse from a JSON string
runtime_web_action_error_response_instance = RuntimeWebActionErrorResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebActionErrorResponse.to_json())

# convert the object into a dict
runtime_web_action_error_response_dict = runtime_web_action_error_response_instance.to_dict()
# create an instance of RuntimeWebActionErrorResponse from a dict
runtime_web_action_error_response_from_dict = RuntimeWebActionErrorResponse.from_dict(runtime_web_action_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


