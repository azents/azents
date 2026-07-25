# GenerationFenceRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_generation** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.generation_fence_request import GenerationFenceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GenerationFenceRequest from a JSON string
generation_fence_request_instance = GenerationFenceRequest.from_json(json)
# print the JSON string representation of the object
print(GenerationFenceRequest.to_json())

# convert the object into a dict
generation_fence_request_dict = generation_fence_request_instance.to_dict()
# create an instance of GenerationFenceRequest from a dict
generation_fence_request_from_dict = GenerationFenceRequest.from_dict(generation_fence_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


