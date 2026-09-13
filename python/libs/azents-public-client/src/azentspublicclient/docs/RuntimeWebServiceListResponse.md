# RuntimeWebServiceListResponse

Bounded service projection page.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeWebServiceResponse]**](RuntimeWebServiceResponse.md) |  | 
**total_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_service_list_response import RuntimeWebServiceListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebServiceListResponse from a JSON string
runtime_web_service_list_response_instance = RuntimeWebServiceListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebServiceListResponse.to_json())

# convert the object into a dict
runtime_web_service_list_response_dict = runtime_web_service_list_response_instance.to_dict()
# create an instance of RuntimeWebServiceListResponse from a dict
runtime_web_service_list_response_from_dict = RuntimeWebServiceListResponse.from_dict(runtime_web_service_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


