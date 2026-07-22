# azentspublicclient.RuntimeProviderEnrollmentV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_provider_enrollment_v1_exchange_credential**](RuntimeProviderEnrollmentV1Api.md#runtime_provider_enrollment_v1_exchange_credential) | **POST** /runtime-provider-enrollment/v1/credentials/exchange | Exchange Credential


# **runtime_provider_enrollment_v1_exchange_credential**
> RuntimeProviderCredentialExchangeResponse runtime_provider_enrollment_v1_exchange_credential(runtime_provider_credential_exchange_request)

Exchange Credential

Exchange one enrollment grant for one Provider credential.

### Example


```python
import azentspublicclient
from azentspublicclient.models.runtime_provider_credential_exchange_request import RuntimeProviderCredentialExchangeRequest
from azentspublicclient.models.runtime_provider_credential_exchange_response import RuntimeProviderCredentialExchangeResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeProviderEnrollmentV1Api(api_client)
    runtime_provider_credential_exchange_request = azentspublicclient.RuntimeProviderCredentialExchangeRequest() # RuntimeProviderCredentialExchangeRequest | 

    try:
        # Exchange Credential
        api_response = api_instance.runtime_provider_enrollment_v1_exchange_credential(runtime_provider_credential_exchange_request)
        print("The response of RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_exchange_credential:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderEnrollmentV1Api->runtime_provider_enrollment_v1_exchange_credential: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_provider_credential_exchange_request** | [**RuntimeProviderCredentialExchangeRequest**](RuntimeProviderCredentialExchangeRequest.md)|  | 

### Return type

[**RuntimeProviderCredentialExchangeResponse**](RuntimeProviderCredentialExchangeResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

