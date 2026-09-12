# RuntimeWebExposureRequest

Idempotent asynchronous exposure request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_exposure_request import RuntimeWebExposureRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebExposureRequest from a JSON string
runtime_web_exposure_request_instance = RuntimeWebExposureRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebExposureRequest.to_json())

# convert the object into a dict
runtime_web_exposure_request_dict = runtime_web_exposure_request_instance.to_dict()
# create an instance of RuntimeWebExposureRequest from a dict
runtime_web_exposure_request_from_dict = RuntimeWebExposureRequest.from_dict(runtime_web_exposure_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


