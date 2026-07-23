# RuntimeProviderEnrollmentGrantIssueRequest

System Admin enrollment grant issuance input.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expires_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_enrollment_grant_issue_request import RuntimeProviderEnrollmentGrantIssueRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderEnrollmentGrantIssueRequest from a JSON string
runtime_provider_enrollment_grant_issue_request_instance = RuntimeProviderEnrollmentGrantIssueRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderEnrollmentGrantIssueRequest.to_json())

# convert the object into a dict
runtime_provider_enrollment_grant_issue_request_dict = runtime_provider_enrollment_grant_issue_request_instance.to_dict()
# create an instance of RuntimeProviderEnrollmentGrantIssueRequest from a dict
runtime_provider_enrollment_grant_issue_request_from_dict = RuntimeProviderEnrollmentGrantIssueRequest.from_dict(runtime_provider_enrollment_grant_issue_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


