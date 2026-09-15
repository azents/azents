# RuntimeWebServiceResponse

Current user-relevant Runtime Web service projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**port** | **int** |  | 
**label** | **str** |  | 
**url** | **str** |  | 
**configuration_state** | **str** |  | 
**on** | **bool** |  | 
**selected_duration_seconds** | **int** |  | 
**expires_at** | **datetime** |  | 
**revision** | **int** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 
**observed_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_service_response import RuntimeWebServiceResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebServiceResponse from a JSON string
runtime_web_service_response_instance = RuntimeWebServiceResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebServiceResponse.to_json())

# convert the object into a dict
runtime_web_service_response_dict = runtime_web_service_response_instance.to_dict()
# create an instance of RuntimeWebServiceResponse from a dict
runtime_web_service_response_from_dict = RuntimeWebServiceResponse.from_dict(runtime_web_service_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


