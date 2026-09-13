# RuntimeWebPrepareRequest

Idempotent endpoint preparation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_prepare_request import RuntimeWebPrepareRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebPrepareRequest from a JSON string
runtime_web_prepare_request_instance = RuntimeWebPrepareRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebPrepareRequest.to_json())

# convert the object into a dict
runtime_web_prepare_request_dict = runtime_web_prepare_request_instance.to_dict()
# create an instance of RuntimeWebPrepareRequest from a dict
runtime_web_prepare_request_from_dict = RuntimeWebPrepareRequest.from_dict(runtime_web_prepare_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


