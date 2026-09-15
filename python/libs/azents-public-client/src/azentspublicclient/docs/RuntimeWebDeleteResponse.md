# RuntimeWebDeleteResponse

Idempotent authorized service deletion outcome.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**deleted** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_delete_response import RuntimeWebDeleteResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebDeleteResponse from a JSON string
runtime_web_delete_response_instance = RuntimeWebDeleteResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebDeleteResponse.to_json())

# convert the object into a dict
runtime_web_delete_response_dict = runtime_web_delete_response_instance.to_dict()
# create an instance of RuntimeWebDeleteResponse from a dict
runtime_web_delete_response_from_dict = RuntimeWebDeleteResponse.from_dict(runtime_web_delete_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


