# RuntimeWebExpectedRevisionRequest

Revision-fenced request control mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_expected_revision_request import RuntimeWebExpectedRevisionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebExpectedRevisionRequest from a JSON string
runtime_web_expected_revision_request_instance = RuntimeWebExpectedRevisionRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebExpectedRevisionRequest.to_json())

# convert the object into a dict
runtime_web_expected_revision_request_dict = runtime_web_expected_revision_request_instance.to_dict()
# create an instance of RuntimeWebExpectedRevisionRequest from a dict
runtime_web_expected_revision_request_from_dict = RuntimeWebExpectedRevisionRequest.from_dict(runtime_web_expected_revision_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


