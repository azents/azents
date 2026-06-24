# azentspublicclient.SecurityV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**security_v1_elevate_with_email**](SecurityV1Api.md#security_v1_elevate_with_email) | **POST** /security/v1/elevate/email | Elevate With Email
[**security_v1_elevate_with_password**](SecurityV1Api.md#security_v1_elevate_with_password) | **POST** /security/v1/elevate/password | Elevate With Password
[**security_v1_get_auth_methods**](SecurityV1Api.md#security_v1_get_auth_methods) | **GET** /security/v1/auth-methods | Get Auth Methods
[**security_v1_get_elevation_methods**](SecurityV1Api.md#security_v1_get_elevation_methods) | **GET** /security/v1/elevation-methods | Get Elevation Methods
[**security_v1_remove_password**](SecurityV1Api.md#security_v1_remove_password) | **DELETE** /security/v1/password | Remove Password
[**security_v1_send_elevation_code**](SecurityV1Api.md#security_v1_send_elevation_code) | **POST** /security/v1/elevate/send-code | Send Elevation Code
[**security_v1_set_password**](SecurityV1Api.md#security_v1_set_password) | **POST** /security/v1/password | Set Password


# **security_v1_elevate_with_email**
> ElevateResponse security_v1_elevate_with_email(elevate_with_email_request)

Elevate With Email

Perform step-up authentication with email OTP.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.elevate_response import ElevateResponse
from azentspublicclient.models.elevate_with_email_request import ElevateWithEmailRequest
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)
    elevate_with_email_request = azentspublicclient.ElevateWithEmailRequest() # ElevateWithEmailRequest |

    try:
        # Elevate With Email
        api_response = api_instance.security_v1_elevate_with_email(elevate_with_email_request)
        print("The response of SecurityV1Api->security_v1_elevate_with_email:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_elevate_with_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **elevate_with_email_request** | [**ElevateWithEmailRequest**](ElevateWithEmailRequest.md)|  |

### Return type

[**ElevateResponse**](ElevateResponse.md)

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

# **security_v1_elevate_with_password**
> ElevateResponse security_v1_elevate_with_password(elevate_with_password_request)

Elevate With Password

Perform step-up authentication with password.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.elevate_response import ElevateResponse
from azentspublicclient.models.elevate_with_password_request import ElevateWithPasswordRequest
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)
    elevate_with_password_request = azentspublicclient.ElevateWithPasswordRequest() # ElevateWithPasswordRequest |

    try:
        # Elevate With Password
        api_response = api_instance.security_v1_elevate_with_password(elevate_with_password_request)
        print("The response of SecurityV1Api->security_v1_elevate_with_password:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_elevate_with_password: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **elevate_with_password_request** | [**ElevateWithPasswordRequest**](ElevateWithPasswordRequest.md)|  |

### Return type

[**ElevateResponse**](ElevateResponse.md)

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

# **security_v1_get_auth_methods**
> GetAuthMethodsResponse security_v1_get_auth_methods()

Get Auth Methods

List available authentication methods.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.get_auth_methods_response import GetAuthMethodsResponse
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)

    try:
        # Get Auth Methods
        api_response = api_instance.security_v1_get_auth_methods()
        print("The response of SecurityV1Api->security_v1_get_auth_methods:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_get_auth_methods: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**GetAuthMethodsResponse**](GetAuthMethodsResponse.md)

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

# **security_v1_get_elevation_methods**
> GetAuthMethodsResponse security_v1_get_elevation_methods()

Get Elevation Methods

List authentication methods available for elevation without elevation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.get_auth_methods_response import GetAuthMethodsResponse
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)

    try:
        # Get Elevation Methods
        api_response = api_instance.security_v1_get_elevation_methods()
        print("The response of SecurityV1Api->security_v1_get_elevation_methods:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_get_elevation_methods: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**GetAuthMethodsResponse**](GetAuthMethodsResponse.md)

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

# **security_v1_remove_password**
> security_v1_remove_password()

Remove Password

Delete password.

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
    api_instance = azentspublicclient.SecurityV1Api(api_client)

    try:
        # Remove Password
        api_instance.security_v1_remove_password()
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_remove_password: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: Not defined

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **security_v1_send_elevation_code**
> SendElevationCodeResponse security_v1_send_elevation_code()

Send Elevation Code

Send an email OTP for step-up authentication.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.send_elevation_code_response import SendElevationCodeResponse
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)

    try:
        # Send Elevation Code
        api_response = api_instance.security_v1_send_elevation_code()
        print("The response of SecurityV1Api->security_v1_send_elevation_code:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_send_elevation_code: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SendElevationCodeResponse**](SendElevationCodeResponse.md)

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

# **security_v1_set_password**
> security_v1_set_password(set_password_request)

Set Password

Set or change password.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.set_password_request import SetPasswordRequest
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
    api_instance = azentspublicclient.SecurityV1Api(api_client)
    set_password_request = azentspublicclient.SetPasswordRequest() # SetPasswordRequest |

    try:
        # Set Password
        api_instance.security_v1_set_password(set_password_request)
    except Exception as e:
        print("Exception when calling SecurityV1Api->security_v1_set_password: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **set_password_request** | [**SetPasswordRequest**](SetPasswordRequest.md)|  |

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)
