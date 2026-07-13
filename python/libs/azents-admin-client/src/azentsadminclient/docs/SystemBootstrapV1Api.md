# azentsadminclient.SystemBootstrapV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**system_bootstrap_v1_bootstrap_first_system_admin**](SystemBootstrapV1Api.md#system_bootstrap_v1_bootstrap_first_system_admin) | **POST** /system/v1/bootstrap/first-admin | Bootstrap First System Admin
[**system_bootstrap_v1_get_system_bootstrap_status**](SystemBootstrapV1Api.md#system_bootstrap_v1_get_system_bootstrap_status) | **GET** /system/v1/bootstrap/status | Get System Bootstrap Status


# **system_bootstrap_v1_bootstrap_first_system_admin**
> SystemBootstrapFirstAdminResponse system_bootstrap_v1_bootstrap_first_system_admin(x_azents_setup_token, system_bootstrap_first_admin_request)

Bootstrap First System Admin

Create the first User and system administrator session.

### Example


```python
import azentsadminclient
from azentsadminclient.models.system_bootstrap_first_admin_request import SystemBootstrapFirstAdminRequest
from azentsadminclient.models.system_bootstrap_first_admin_response import SystemBootstrapFirstAdminResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemBootstrapV1Api(api_client)
    x_azents_setup_token = 'x_azents_setup_token_example' # str |
    system_bootstrap_first_admin_request = azentsadminclient.SystemBootstrapFirstAdminRequest() # SystemBootstrapFirstAdminRequest |

    try:
        # Bootstrap First System Admin
        api_response = api_instance.system_bootstrap_v1_bootstrap_first_system_admin(x_azents_setup_token, system_bootstrap_first_admin_request)
        print("The response of SystemBootstrapV1Api->system_bootstrap_v1_bootstrap_first_system_admin:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemBootstrapV1Api->system_bootstrap_v1_bootstrap_first_system_admin: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **x_azents_setup_token** | **str**|  |
 **system_bootstrap_first_admin_request** | [**SystemBootstrapFirstAdminRequest**](SystemBootstrapFirstAdminRequest.md)|  |

### Return type

[**SystemBootstrapFirstAdminResponse**](SystemBootstrapFirstAdminResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **system_bootstrap_v1_get_system_bootstrap_status**
> SystemBootstrapStatusResponse system_bootstrap_v1_get_system_bootstrap_status()

Get System Bootstrap Status

Return whether initial system bootstrap is available.

### Example


```python
import azentsadminclient
from azentsadminclient.models.system_bootstrap_status_response import SystemBootstrapStatusResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.SystemBootstrapV1Api(api_client)

    try:
        # Get System Bootstrap Status
        api_response = api_instance.system_bootstrap_v1_get_system_bootstrap_status()
        print("The response of SystemBootstrapV1Api->system_bootstrap_v1_get_system_bootstrap_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SystemBootstrapV1Api->system_bootstrap_v1_get_system_bootstrap_status: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SystemBootstrapStatusResponse**](SystemBootstrapStatusResponse.md)

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
