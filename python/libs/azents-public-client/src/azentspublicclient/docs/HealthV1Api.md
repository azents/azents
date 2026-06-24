# azentspublicclient.HealthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**health_v1_liveness**](HealthV1Api.md#health_v1_liveness) | **GET** /health/v1/liveness | Liveness
[**health_v1_readiness**](HealthV1Api.md#health_v1_readiness) | **GET** /health/v1/readiness | Readiness


# **health_v1_liveness**
> HealthStatus health_v1_liveness()

Liveness

Return the server liveness status.

This is the endpoint for the Kubernetes liveness probe.

### Example


```python
import azentspublicclient
from azentspublicclient.models.health_status import HealthStatus
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
    api_instance = azentspublicclient.HealthV1Api(api_client)

    try:
        # Liveness
        api_response = api_instance.health_v1_liveness()
        print("The response of HealthV1Api->health_v1_liveness:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling HealthV1Api->health_v1_liveness: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**HealthStatus**](HealthStatus.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **health_v1_readiness**
> HealthStatus health_v1_readiness()

Readiness

Return the server readiness status.

This is the endpoint for the Kubernetes readiness probe.

### Example


```python
import azentspublicclient
from azentspublicclient.models.health_status import HealthStatus
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
    api_instance = azentspublicclient.HealthV1Api(api_client)

    try:
        # Readiness
        api_response = api_instance.health_v1_readiness()
        print("The response of HealthV1Api->health_v1_readiness:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling HealthV1Api->health_v1_readiness: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**HealthStatus**](HealthStatus.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)
