# azentspublicclient.RuntimeProviderV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_provider_v1_list_workspace_runtime_providers**](RuntimeProviderV1Api.md#runtime_provider_v1_list_workspace_runtime_providers) | **GET** /runtime-provider/v1/workspaces/{handle}/providers | List Workspace Runtime Providers


# **runtime_provider_v1_list_workspace_runtime_providers**
> RuntimeProviderOptionListResponse runtime_provider_v1_list_workspace_runtime_providers(handle)

List Workspace Runtime Providers

List eligible Runtime Providers for a Workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.runtime_provider_option_list_response import RuntimeProviderOptionListResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.RuntimeProviderV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # List Workspace Runtime Providers
        api_response = api_instance.runtime_provider_v1_list_workspace_runtime_providers(handle)
        print("The response of RuntimeProviderV1Api->runtime_provider_v1_list_workspace_runtime_providers:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderV1Api->runtime_provider_v1_list_workspace_runtime_providers: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**RuntimeProviderOptionListResponse**](RuntimeProviderOptionListResponse.md)

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

