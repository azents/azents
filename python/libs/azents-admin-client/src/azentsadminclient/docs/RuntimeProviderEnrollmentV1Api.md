# azentsadminclient.RuntimeProviderEnrollmentV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_provider_enrollment_v1_issue_enrollment_grant**](RuntimeProviderEnrollmentV1Api.md#runtime_provider_enrollment_v1_issue_enrollment_grant) | **POST** /runtime-provider-enrollment/v1/runtime-providers/{provider_id}/enrollment-grants | Issue Enrollment Grant
[**runtime_provider_enrollment_v1_revoke_credential**](RuntimeProviderEnrollmentV1Api.md#runtime_provider_enrollment_v1_revoke_credential) | **DELETE** /runtime-provider-enrollment/v1/runtime-provider-credentials/{credential_id} | Revoke Credential


# **runtime_provider_enrollment_v1_issue_enrollment_grant**
> RuntimeProviderEnrollmentGrantIssueResponse runtime_provider_enrollment_v1_issue_enrollment_grant(provider_id, runtime_provider_enrollment_grant_issue_request)

Issue Enrollment Grant

Issue one-time Provider enrollment authority for a Deployment Operator.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_enrollment_grant_issue_request import RuntimeProviderEnrollmentGrantIssueRequest
from azentsadminclient.models.runtime_provider_enrollment_grant_issue_response import RuntimeProviderEnrollmentGrantIssueResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeProviderEnrollmentV1Api(api_client)
    provider_id = 'provider_id_example' # str | 
    runtime_provider_enrollment_grant_issue_request = azentsadminclient.RuntimeProviderEnrollmentGrantIssueRequest() # RuntimeProviderEnrollmentGrantIssueRequest | 

    try:
        # Issue Enrollment Grant
        api_response = api_instance.runtime_provider_enrollment_v1_issue_enrollment_grant(provider_id, runtime_provider_enrollment_grant_issue_request)
        print("The response of RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_issue_enrollment_grant:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_issue_enrollment_grant: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **provider_id** | **str**|  | 
 **runtime_provider_enrollment_grant_issue_request** | [**RuntimeProviderEnrollmentGrantIssueRequest**](RuntimeProviderEnrollmentGrantIssueRequest.md)|  | 

### Return type

[**RuntimeProviderEnrollmentGrantIssueResponse**](RuntimeProviderEnrollmentGrantIssueResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_provider_enrollment_v1_revoke_credential**
> RuntimeProviderCredentialRevokeResponse runtime_provider_enrollment_v1_revoke_credential(credential_id)

Revoke Credential

Revoke one Provider credential without deleting its audit history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_credential_revoke_response import RuntimeProviderCredentialRevokeResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeProviderEnrollmentV1Api(api_client)
    credential_id = 'credential_id_example' # str | 

    try:
        # Revoke Credential
        api_response = api_instance.runtime_provider_enrollment_v1_revoke_credential(credential_id)
        print("The response of RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_revoke_credential:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_revoke_credential: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **credential_id** | **str**|  | 

### Return type

[**RuntimeProviderCredentialRevokeResponse**](RuntimeProviderCredentialRevokeResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

