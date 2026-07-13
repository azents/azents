# azentsadminclient.ModelCatalogV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**model_catalog_v1_list_system_model_catalogs**](ModelCatalogV1Api.md#model_catalog_v1_list_system_model_catalogs) | **GET** /model-catalog/v1/system-catalogs | List System Model Catalogs
[**model_catalog_v1_refresh_system_model_catalog**](ModelCatalogV1Api.md#model_catalog_v1_refresh_system_model_catalog) | **POST** /model-catalog/v1/system-catalogs/{provider}/refresh | Refresh System Model Catalog
[**model_catalog_v1_refresh_system_model_catalogs**](ModelCatalogV1Api.md#model_catalog_v1_refresh_system_model_catalogs) | **POST** /model-catalog/v1/system-catalogs/refresh | Refresh System Model Catalogs


# **model_catalog_v1_list_system_model_catalogs**
> SystemModelCatalogListResponse model_catalog_v1_list_system_model_catalogs()

List System Model Catalogs

List supported system model catalogs.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_model_catalog_list_response import SystemModelCatalogListResponse
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
    api_instance = azentsadminclient.ModelCatalogV1Api(api_client)

    try:
        # List System Model Catalogs
        api_response = api_instance.model_catalog_v1_list_system_model_catalogs()
        print("The response of ModelCatalogV1Api->model_catalog_v1_list_system_model_catalogs:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ModelCatalogV1Api->model_catalog_v1_list_system_model_catalogs: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SystemModelCatalogListResponse**](SystemModelCatalogListResponse.md)

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

# **model_catalog_v1_refresh_system_model_catalog**
> SystemModelCatalogRefreshResponse model_catalog_v1_refresh_system_model_catalog(provider)

Refresh System Model Catalog

Refresh one system model catalog projection by provider.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.llm_provider import LLMProvider
from azentsadminclient.models.system_model_catalog_refresh_response import SystemModelCatalogRefreshResponse
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
    api_instance = azentsadminclient.ModelCatalogV1Api(api_client)
    provider = azentsadminclient.LLMProvider() # LLMProvider |

    try:
        # Refresh System Model Catalog
        api_response = api_instance.model_catalog_v1_refresh_system_model_catalog(provider)
        print("The response of ModelCatalogV1Api->model_catalog_v1_refresh_system_model_catalog:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ModelCatalogV1Api->model_catalog_v1_refresh_system_model_catalog: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **provider** | [**LLMProvider**](.md)|  |

### Return type

[**SystemModelCatalogRefreshResponse**](SystemModelCatalogRefreshResponse.md)

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

# **model_catalog_v1_refresh_system_model_catalogs**
> SystemModelCatalogRefreshListResponse model_catalog_v1_refresh_system_model_catalogs()

Refresh System Model Catalogs

Refresh all system model catalog projections.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.system_model_catalog_refresh_list_response import SystemModelCatalogRefreshListResponse
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
    api_instance = azentsadminclient.ModelCatalogV1Api(api_client)

    try:
        # Refresh System Model Catalogs
        api_response = api_instance.model_catalog_v1_refresh_system_model_catalogs()
        print("The response of ModelCatalogV1Api->model_catalog_v1_refresh_system_model_catalogs:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ModelCatalogV1Api->model_catalog_v1_refresh_system_model_catalogs: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SystemModelCatalogRefreshListResponse**](SystemModelCatalogRefreshListResponse.md)

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
