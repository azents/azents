# RuntimeProviderEnrollmentGrantIssueResponse

One-time enrollment grant returned only to a System Admin.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**grant_id** | **str** |  | 
**provider_id** | **str** |  | 
**secret** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_enrollment_grant_issue_response import RuntimeProviderEnrollmentGrantIssueResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderEnrollmentGrantIssueResponse from a JSON string
runtime_provider_enrollment_grant_issue_response_instance = RuntimeProviderEnrollmentGrantIssueResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderEnrollmentGrantIssueResponse.to_json())

# convert the object into a dict
runtime_provider_enrollment_grant_issue_response_dict = runtime_provider_enrollment_grant_issue_response_instance.to_dict()
# create an instance of RuntimeProviderEnrollmentGrantIssueResponse from a dict
runtime_provider_enrollment_grant_issue_response_from_dict = RuntimeProviderEnrollmentGrantIssueResponse.from_dict(runtime_provider_enrollment_grant_issue_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


