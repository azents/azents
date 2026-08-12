# RuntimeInfrastructureProfileDeleteRequest

Exact optimistic infrastructure Profile deletion request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_delete_request import RuntimeInfrastructureProfileDeleteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileDeleteRequest from a JSON string
runtime_infrastructure_profile_delete_request_instance = RuntimeInfrastructureProfileDeleteRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileDeleteRequest.to_json())

# convert the object into a dict
runtime_infrastructure_profile_delete_request_dict = runtime_infrastructure_profile_delete_request_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileDeleteRequest from a dict
runtime_infrastructure_profile_delete_request_from_dict = RuntimeInfrastructureProfileDeleteRequest.from_dict(runtime_infrastructure_profile_delete_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


