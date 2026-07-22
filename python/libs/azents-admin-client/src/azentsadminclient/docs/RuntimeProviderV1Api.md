# azentsadminclient.RuntimeProviderV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_provider_v1_get_runtime_provider**](RuntimeProviderV1Api.md#runtime_provider_v1_get_runtime_provider) | **GET** /runtime-provider/v1/providers/{provider_id} | Get Runtime Provider
[**runtime_provider_v1_list_runtime_providers**](RuntimeProviderV1Api.md#runtime_provider_v1_list_runtime_providers) | **GET** /runtime-provider/v1/providers | List Runtime Providers
[**runtime_provider_v1_replace_runtime_provider_availability**](RuntimeProviderV1Api.md#runtime_provider_v1_replace_runtime_provider_availability) | **PUT** /runtime-provider/v1/providers/{provider_id}/availability | Replace Runtime Provider Availability
[**runtime_provider_v1_update_runtime_provider_policy**](RuntimeProviderV1Api.md#runtime_provider_v1_update_runtime_provider_policy) | **PATCH** /runtime-provider/v1/providers/{provider_id}/policy | Update Runtime Provider Policy


# **runtime_provider_v1_get_runtime_provider**
> RuntimeProviderResponse runtime_provider_v1_get_runtime_provider(provider_id)

Get Runtime Provider

Inspect one durable Runtime Provider.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_response import RuntimeProviderResponse
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
    api_instance = azentsadminclient.RuntimeProviderV1Api(api_client)
    provider_id = 'provider_id_example' # str | 

    try:
        # Get Runtime Provider
        api_response = api_instance.runtime_provider_v1_get_runtime_provider(provider_id)
        print("The response of RuntimeProviderV1Api->runtime_provider_v1_get_runtime_provider:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderV1Api->runtime_provider_v1_get_runtime_provider: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **provider_id** | **str**|  | 

### Return type

[**RuntimeProviderResponse**](RuntimeProviderResponse.md)

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

# **runtime_provider_v1_list_runtime_providers**
> RuntimeProviderListResponse runtime_provider_v1_list_runtime_providers()

List Runtime Providers

List all durable Runtime Providers for System Admin operations.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_list_response import RuntimeProviderListResponse
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
    api_instance = azentsadminclient.RuntimeProviderV1Api(api_client)

    try:
        # List Runtime Providers
        api_response = api_instance.runtime_provider_v1_list_runtime_providers()
        print("The response of RuntimeProviderV1Api->runtime_provider_v1_list_runtime_providers:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderV1Api->runtime_provider_v1_list_runtime_providers: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**RuntimeProviderListResponse**](RuntimeProviderListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_provider_v1_replace_runtime_provider_availability**
> RuntimeProviderResponse runtime_provider_v1_replace_runtime_provider_availability(provider_id, runtime_provider_availability_request)

Replace Runtime Provider Availability

Replace selected-Workspace availability for one Provider.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_availability_request import RuntimeProviderAvailabilityRequest
from azentsadminclient.models.runtime_provider_response import RuntimeProviderResponse
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
    api_instance = azentsadminclient.RuntimeProviderV1Api(api_client)
    provider_id = 'provider_id_example' # str | 
    runtime_provider_availability_request = azentsadminclient.RuntimeProviderAvailabilityRequest() # RuntimeProviderAvailabilityRequest | 

    try:
        # Replace Runtime Provider Availability
        api_response = api_instance.runtime_provider_v1_replace_runtime_provider_availability(provider_id, runtime_provider_availability_request)
        print("The response of RuntimeProviderV1Api->runtime_provider_v1_replace_runtime_provider_availability:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderV1Api->runtime_provider_v1_replace_runtime_provider_availability: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **provider_id** | **str**|  | 
 **runtime_provider_availability_request** | [**RuntimeProviderAvailabilityRequest**](RuntimeProviderAvailabilityRequest.md)|  | 

### Return type

[**RuntimeProviderResponse**](RuntimeProviderResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **runtime_provider_v1_update_runtime_provider_policy**
> RuntimeProviderResponse runtime_provider_v1_update_runtime_provider_policy(provider_id, runtime_provider_policy_update_request)

Update Runtime Provider Policy

Update mutable Provider policy without moving existing Runtimes.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_provider_policy_update_request import RuntimeProviderPolicyUpdateRequest
from azentsadminclient.models.runtime_provider_response import RuntimeProviderResponse
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
    api_instance = azentsadminclient.RuntimeProviderV1Api(api_client)
    provider_id = 'provider_id_example' # str | 
    runtime_provider_policy_update_request = azentsadminclient.RuntimeProviderPolicyUpdateRequest() # RuntimeProviderPolicyUpdateRequest | 

    try:
        # Update Runtime Provider Policy
        api_response = api_instance.runtime_provider_v1_update_runtime_provider_policy(provider_id, runtime_provider_policy_update_request)
        print("The response of RuntimeProviderV1Api->runtime_provider_v1_update_runtime_provider_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeProviderV1Api->runtime_provider_v1_update_runtime_provider_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **provider_id** | **str**|  | 
 **runtime_provider_policy_update_request** | [**RuntimeProviderPolicyUpdateRequest**](RuntimeProviderPolicyUpdateRequest.md)|  | 

### Return type

[**RuntimeProviderResponse**](RuntimeProviderResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

