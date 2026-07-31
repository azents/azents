# RuntimeRecreationCreateRequest

Create one optimistic bounded recreation operation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**concurrency_limit** | **int** |  | [optional] [default to 5]

## Example

```python
from azentspublicclient.models.runtime_recreation_create_request import RuntimeRecreationCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeRecreationCreateRequest from a JSON string
runtime_recreation_create_request_instance = RuntimeRecreationCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeRecreationCreateRequest.to_json())

# convert the object into a dict
runtime_recreation_create_request_dict = runtime_recreation_create_request_instance.to_dict()
# create an instance of RuntimeRecreationCreateRequest from a dict
runtime_recreation_create_request_from_dict = RuntimeRecreationCreateRequest.from_dict(runtime_recreation_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


