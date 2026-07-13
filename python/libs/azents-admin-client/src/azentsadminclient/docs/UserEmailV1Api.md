# azentsadminclient.UserEmailV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**useremail_v1_create_email**](UserEmailV1Api.md#useremail_v1_create_email) | **POST** /user-email/v1/users/{user_id}/emails | Create Email
[**useremail_v1_delete_email**](UserEmailV1Api.md#useremail_v1_delete_email) | **DELETE** /user-email/v1/emails/{email_id} | Delete Email
[**useremail_v1_list_emails**](UserEmailV1Api.md#useremail_v1_list_emails) | **GET** /user-email/v1/emails | List Emails
[**useremail_v1_list_emails_by_user**](UserEmailV1Api.md#useremail_v1_list_emails_by_user) | **GET** /user-email/v1/users/{user_id}/emails | List Emails By User


# **useremail_v1_create_email**
> UserEmailResponse useremail_v1_create_email(user_id, user_email_create_request)

Create Email

Create a UserEmail.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.user_email_create_request import UserEmailCreateRequest
from azentsadminclient.models.user_email_response import UserEmailResponse
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
    api_instance = azentsadminclient.UserEmailV1Api(api_client)
    user_id = 'user_id_example' # str |
    user_email_create_request = azentsadminclient.UserEmailCreateRequest() # UserEmailCreateRequest |

    try:
        # Create Email
        api_response = api_instance.useremail_v1_create_email(user_id, user_email_create_request)
        print("The response of UserEmailV1Api->useremail_v1_create_email:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserEmailV1Api->useremail_v1_create_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  |
 **user_email_create_request** | [**UserEmailCreateRequest**](UserEmailCreateRequest.md)|  |

### Return type

[**UserEmailResponse**](UserEmailResponse.md)

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

# **useremail_v1_delete_email**
> useremail_v1_delete_email(email_id)

Delete Email

Delete a UserEmail.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
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
    api_instance = azentsadminclient.UserEmailV1Api(api_client)
    email_id = 'email_id_example' # str |

    try:
        # Delete Email
        api_instance.useremail_v1_delete_email(email_id)
    except Exception as e:
        print("Exception when calling UserEmailV1Api->useremail_v1_delete_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **email_id** | **str**|  |

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

# **useremail_v1_list_emails**
> UserEmailListResponse useremail_v1_list_emails(offset=offset, limit=limit)

List Emails

List all UserEmail records.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.user_email_list_response import UserEmailListResponse
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
    api_instance = azentsadminclient.UserEmailV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Emails
        api_response = api_instance.useremail_v1_list_emails(offset=offset, limit=limit)
        print("The response of UserEmailV1Api->useremail_v1_list_emails:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserEmailV1Api->useremail_v1_list_emails: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**UserEmailListResponse**](UserEmailListResponse.md)

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

# **useremail_v1_list_emails_by_user**
> UserEmailListResponse useremail_v1_list_emails_by_user(user_id)

List Emails By User

List UserEmail records by User ID.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.user_email_list_response import UserEmailListResponse
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
    api_instance = azentsadminclient.UserEmailV1Api(api_client)
    user_id = 'user_id_example' # str |

    try:
        # List Emails By User
        api_response = api_instance.useremail_v1_list_emails_by_user(user_id)
        print("The response of UserEmailV1Api->useremail_v1_list_emails_by_user:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling UserEmailV1Api->useremail_v1_list_emails_by_user: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **user_id** | **str**|  |

### Return type

[**UserEmailListResponse**](UserEmailListResponse.md)

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
