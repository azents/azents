# azentspublicclient.LLMProviderIntegrationV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**llm_provider_integration_v1_create_integration**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_create_integration) | **POST** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations | Create Integration
[**llm_provider_integration_v1_delete_integration**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_delete_integration) | **DELETE** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id} | Delete Integration
[**llm_provider_integration_v1_get_integration**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_get_integration) | **GET** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id} | Get Integration
[**llm_provider_integration_v1_get_subscription_usage**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_get_subscription_usage) | **GET** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/subscription-usage | Get Subscription Usage
[**llm_provider_integration_v1_list_integration_catalog_entries**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_list_integration_catalog_entries) | **GET** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/catalog-entries | List Integration Catalog Entries
[**llm_provider_integration_v1_list_integration_providers**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_list_integration_providers) | **GET** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/providers | List Integration Providers
[**llm_provider_integration_v1_list_integrations**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_list_integrations) | **GET** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations | List Integrations
[**llm_provider_integration_v1_sync_integration_catalog**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_sync_integration_catalog) | **POST** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/catalog-sync | Sync Integration Catalog
[**llm_provider_integration_v1_update_integration**](LLMProviderIntegrationV1Api.md#llm_provider_integration_v1_update_integration) | **PATCH** /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id} | Update Integration


# **llm_provider_integration_v1_create_integration**
> LLMProviderIntegrationResponse llm_provider_integration_v1_create_integration(handle, llm_provider_integration_create_request)

Create Integration

Create an LLM Provider Integration.

Requires LLM integration write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.llm_provider_integration_create_request import LLMProviderIntegrationCreateRequest
from azentspublicclient.models.llm_provider_integration_response import LLMProviderIntegrationResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    handle = 'handle_example' # str |
    llm_provider_integration_create_request = azentspublicclient.LLMProviderIntegrationCreateRequest() # LLMProviderIntegrationCreateRequest |

    try:
        # Create Integration
        api_response = api_instance.llm_provider_integration_v1_create_integration(handle, llm_provider_integration_create_request)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_create_integration:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_create_integration: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **llm_provider_integration_create_request** | [**LLMProviderIntegrationCreateRequest**](LLMProviderIntegrationCreateRequest.md)|  |

### Return type

[**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md)

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

# **llm_provider_integration_v1_delete_integration**
> llm_provider_integration_v1_delete_integration(integration_id, handle)

Delete Integration

Delete an LLM Provider Integration.

Requires LLM integration write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Delete Integration
        api_instance.llm_provider_integration_v1_delete_integration(integration_id, handle)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_delete_integration: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **llm_provider_integration_v1_get_integration**
> LLMProviderIntegrationResponse llm_provider_integration_v1_get_integration(integration_id, handle)

Get Integration

Get LLM Provider Integration details.

Requires LLM integration read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.llm_provider_integration_response import LLMProviderIntegrationResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Get Integration
        api_response = api_instance.llm_provider_integration_v1_get_integration(integration_id, handle)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_get_integration:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_get_integration: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md)

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

# **llm_provider_integration_v1_get_subscription_usage**
> ResponseLlmProviderIntegrationV1GetSubscriptionUsage llm_provider_integration_v1_get_subscription_usage(integration_id, handle)

Get Subscription Usage

Read live subscription usage for one LLM provider integration.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.response_llm_provider_integration_v1_get_subscription_usage import ResponseLlmProviderIntegrationV1GetSubscriptionUsage
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Get Subscription Usage
        api_response = api_instance.llm_provider_integration_v1_get_subscription_usage(integration_id, handle)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_get_subscription_usage:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_get_subscription_usage: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ResponseLlmProviderIntegrationV1GetSubscriptionUsage**](ResponseLlmProviderIntegrationV1GetSubscriptionUsage.md)

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

# **llm_provider_integration_v1_list_integration_catalog_entries**
> ModelCatalogEntryListResponse llm_provider_integration_v1_list_integration_catalog_entries(integration_id, handle, search=search, limit=limit, offset=offset)

List Integration Catalog Entries

List stored model catalog entries for an integration.

Requires LLM integration read permission.
This endpoint reads only stored projections and never calls providers.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.model_catalog_entry_list_response import ModelCatalogEntryListResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |
    search = 'search_example' # str |  (optional)
    limit = 50 # int |  (optional) (default to 50)
    offset = 0 # int |  (optional) (default to 0)

    try:
        # List Integration Catalog Entries
        api_response = api_instance.llm_provider_integration_v1_list_integration_catalog_entries(integration_id, handle, search=search, limit=limit, offset=offset)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integration_catalog_entries:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integration_catalog_entries: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |
 **search** | **str**|  | [optional]
 **limit** | **int**|  | [optional] [default to 50]
 **offset** | **int**|  | [optional] [default to 0]

### Return type

[**ModelCatalogEntryListResponse**](ModelCatalogEntryListResponse.md)

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

# **llm_provider_integration_v1_list_integration_providers**
> LLMProviderCapabilityListResponse llm_provider_integration_v1_list_integration_providers(handle)

List Integration Providers

List provider options available to create in this workspace.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.llm_provider_capability_list_response import LLMProviderCapabilityListResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Integration Providers
        api_response = api_instance.llm_provider_integration_v1_list_integration_providers(handle)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integration_providers:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integration_providers: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**LLMProviderCapabilityListResponse**](LLMProviderCapabilityListResponse.md)

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

# **llm_provider_integration_v1_list_integrations**
> LLMProviderIntegrationListResponse llm_provider_integration_v1_list_integrations(handle)

List Integrations

List LLM Provider Integrations in a workspace.

Requires LLM integration read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.llm_provider_integration_list_response import LLMProviderIntegrationListResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # List Integrations
        api_response = api_instance.llm_provider_integration_v1_list_integrations(handle)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integrations:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_list_integrations: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**LLMProviderIntegrationListResponse**](LLMProviderIntegrationListResponse.md)

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

# **llm_provider_integration_v1_sync_integration_catalog**
> ModelCatalogSyncResponse llm_provider_integration_v1_sync_integration_catalog(integration_id, handle)

Sync Integration Catalog

Synchronize stored model catalog entries for an integration.

Requires LLM integration write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.model_catalog_sync_response import ModelCatalogSyncResponse
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Sync Integration Catalog
        api_response = api_instance.llm_provider_integration_v1_sync_integration_catalog(integration_id, handle)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_sync_integration_catalog:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_sync_integration_catalog: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |

### Return type

[**ModelCatalogSyncResponse**](ModelCatalogSyncResponse.md)

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

# **llm_provider_integration_v1_update_integration**
> LLMProviderIntegrationResponse llm_provider_integration_v1_update_integration(integration_id, handle, llm_provider_integration_update_request)

Update Integration

Update an LLM Provider Integration.

Requires LLM integration write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.llm_provider_integration_response import LLMProviderIntegrationResponse
from azentspublicclient.models.llm_provider_integration_update_request import LLMProviderIntegrationUpdateRequest
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
    api_instance = azentspublicclient.LLMProviderIntegrationV1Api(api_client)
    integration_id = 'integration_id_example' # str |
    handle = 'handle_example' # str |
    llm_provider_integration_update_request = azentspublicclient.LLMProviderIntegrationUpdateRequest() # LLMProviderIntegrationUpdateRequest |

    try:
        # Update Integration
        api_response = api_instance.llm_provider_integration_v1_update_integration(integration_id, handle, llm_provider_integration_update_request)
        print("The response of LLMProviderIntegrationV1Api->llm_provider_integration_v1_update_integration:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling LLMProviderIntegrationV1Api->llm_provider_integration_v1_update_integration: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **integration_id** | **str**|  |
 **handle** | **str**|  |
 **llm_provider_integration_update_request** | [**LLMProviderIntegrationUpdateRequest**](LLMProviderIntegrationUpdateRequest.md)|  |

### Return type

[**LLMProviderIntegrationResponse**](LLMProviderIntegrationResponse.md)

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
