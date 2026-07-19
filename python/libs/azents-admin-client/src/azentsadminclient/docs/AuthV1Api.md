# azentsadminclient.AuthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**auth_v1_create_password_reset_token**](AuthV1Api.md#auth_v1_create_password_reset_token) | **POST** /auth/v1/password-reset-tokens | Create Password Reset Token
[**auth_v1_create_signup_token**](AuthV1Api.md#auth_v1_create_signup_token) | **POST** /auth/v1/signup-tokens | Create Signup Token
[**auth_v1_get_email_verification**](AuthV1Api.md#auth_v1_get_email_verification) | **GET** /auth/v1/email-verifications/{verification_id} | Get Email Verification
[**auth_v1_get_email_verification_by_email**](AuthV1Api.md#auth_v1_get_email_verification_by_email) | **GET** /auth/v1/email-verifications/by-email | Get Email Verification By Email
[**auth_v1_list_email_verifications**](AuthV1Api.md#auth_v1_list_email_verifications) | **GET** /auth/v1/email-verifications | List Email Verifications
[**auth_v1_list_email_verifications_by_email**](AuthV1Api.md#auth_v1_list_email_verifications_by_email) | **GET** /auth/v1/email-verifications/by-email/{email} | List Email Verifications By Email
[**auth_v1_list_password_reset_tokens**](AuthV1Api.md#auth_v1_list_password_reset_tokens) | **GET** /auth/v1/password-reset-tokens | List Password Reset Tokens
[**auth_v1_list_signup_tokens**](AuthV1Api.md#auth_v1_list_signup_tokens) | **GET** /auth/v1/signup-tokens | List Signup Tokens
[**auth_v1_revoke_password_reset_token**](AuthV1Api.md#auth_v1_revoke_password_reset_token) | **DELETE** /auth/v1/password-reset-tokens/{token_id} | Revoke Password Reset Token
[**auth_v1_revoke_signup_token**](AuthV1Api.md#auth_v1_revoke_signup_token) | **DELETE** /auth/v1/signup-tokens/{token_id} | Revoke Signup Token


# **auth_v1_create_password_reset_token**
> CreatePasswordResetTokenResponse auth_v1_create_password_reset_token(create_password_reset_token_request)

Create Password Reset Token

Create a password reset token.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.create_password_reset_token_request import CreatePasswordResetTokenRequest
from azentsadminclient.models.create_password_reset_token_response import CreatePasswordResetTokenResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    create_password_reset_token_request = azentsadminclient.CreatePasswordResetTokenRequest() # CreatePasswordResetTokenRequest | 

    try:
        # Create Password Reset Token
        api_response = api_instance.auth_v1_create_password_reset_token(create_password_reset_token_request)
        print("The response of AuthV1Api->auth_v1_create_password_reset_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_create_password_reset_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **create_password_reset_token_request** | [**CreatePasswordResetTokenRequest**](CreatePasswordResetTokenRequest.md)|  | 

### Return type

[**CreatePasswordResetTokenResponse**](CreatePasswordResetTokenResponse.md)

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

# **auth_v1_create_signup_token**
> CreateSignupTokenResponse auth_v1_create_signup_token(create_signup_token_request)

Create Signup Token

Create a signup token.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.create_signup_token_request import CreateSignupTokenRequest
from azentsadminclient.models.create_signup_token_response import CreateSignupTokenResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    create_signup_token_request = azentsadminclient.CreateSignupTokenRequest() # CreateSignupTokenRequest | 

    try:
        # Create Signup Token
        api_response = api_instance.auth_v1_create_signup_token(create_signup_token_request)
        print("The response of AuthV1Api->auth_v1_create_signup_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_create_signup_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **create_signup_token_request** | [**CreateSignupTokenRequest**](CreateSignupTokenRequest.md)|  | 

### Return type

[**CreateSignupTokenResponse**](CreateSignupTokenResponse.md)

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

# **auth_v1_get_email_verification**
> EmailVerificationResponse auth_v1_get_email_verification(verification_id)

Get Email Verification

Get an EmailVerification by ID.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.email_verification_response import EmailVerificationResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    verification_id = 'verification_id_example' # str | 

    try:
        # Get Email Verification
        api_response = api_instance.auth_v1_get_email_verification(verification_id)
        print("The response of AuthV1Api->auth_v1_get_email_verification:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_get_email_verification: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **verification_id** | **str**|  | 

### Return type

[**EmailVerificationResponse**](EmailVerificationResponse.md)

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

# **auth_v1_get_email_verification_by_email**
> EmailVerificationResponse auth_v1_get_email_verification_by_email(email, csrf_token)

Get Email Verification By Email

Get an EmailVerification by email and CSRF token.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.email_verification_response import EmailVerificationResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    email = 'email_example' # str | 
    csrf_token = 'csrf_token_example' # str | 

    try:
        # Get Email Verification By Email
        api_response = api_instance.auth_v1_get_email_verification_by_email(email, csrf_token)
        print("The response of AuthV1Api->auth_v1_get_email_verification_by_email:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_get_email_verification_by_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **email** | **str**|  | 
 **csrf_token** | **str**|  | 

### Return type

[**EmailVerificationResponse**](EmailVerificationResponse.md)

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

# **auth_v1_list_email_verifications**
> EmailVerificationListResponse auth_v1_list_email_verifications(offset=offset, limit=limit)

List Email Verifications

List EmailVerification records.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.email_verification_list_response import EmailVerificationListResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Email Verifications
        api_response = api_instance.auth_v1_list_email_verifications(offset=offset, limit=limit)
        print("The response of AuthV1Api->auth_v1_list_email_verifications:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_list_email_verifications: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**EmailVerificationListResponse**](EmailVerificationListResponse.md)

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

# **auth_v1_list_email_verifications_by_email**
> EmailVerificationListResponse auth_v1_list_email_verifications_by_email(email, offset=offset, limit=limit)

List Email Verifications By Email

List active EmailVerification records by email.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.email_verification_list_response import EmailVerificationListResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    email = 'email_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 20 # int |  (optional) (default to 20)

    try:
        # List Email Verifications By Email
        api_response = api_instance.auth_v1_list_email_verifications_by_email(email, offset=offset, limit=limit)
        print("The response of AuthV1Api->auth_v1_list_email_verifications_by_email:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_list_email_verifications_by_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **email** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 20]

### Return type

[**EmailVerificationListResponse**](EmailVerificationListResponse.md)

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

# **auth_v1_list_password_reset_tokens**
> PasswordResetTokenListResponse auth_v1_list_password_reset_tokens(offset=offset, limit=limit)

List Password Reset Tokens

List password reset tokens.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.password_reset_token_list_response import PasswordResetTokenListResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Password Reset Tokens
        api_response = api_instance.auth_v1_list_password_reset_tokens(offset=offset, limit=limit)
        print("The response of AuthV1Api->auth_v1_list_password_reset_tokens:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_list_password_reset_tokens: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**PasswordResetTokenListResponse**](PasswordResetTokenListResponse.md)

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

# **auth_v1_list_signup_tokens**
> SignupTokenListResponse auth_v1_list_signup_tokens(offset=offset, limit=limit)

List Signup Tokens

List signup tokens.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.signup_token_list_response import SignupTokenListResponse
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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Signup Tokens
        api_response = api_instance.auth_v1_list_signup_tokens(offset=offset, limit=limit)
        print("The response of AuthV1Api->auth_v1_list_signup_tokens:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_list_signup_tokens: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**SignupTokenListResponse**](SignupTokenListResponse.md)

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

# **auth_v1_revoke_password_reset_token**
> auth_v1_revoke_password_reset_token(token_id)

Revoke Password Reset Token

Revoke a password reset token.

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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    token_id = 'token_id_example' # str | 

    try:
        # Revoke Password Reset Token
        api_instance.auth_v1_revoke_password_reset_token(token_id)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_revoke_password_reset_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **token_id** | **str**|  | 

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

# **auth_v1_revoke_signup_token**
> auth_v1_revoke_signup_token(token_id)

Revoke Signup Token

Revoke a signup token.

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
    api_instance = azentsadminclient.AuthV1Api(api_client)
    token_id = 'token_id_example' # str | 

    try:
        # Revoke Signup Token
        api_instance.auth_v1_revoke_signup_token(token_id)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_revoke_signup_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **token_id** | **str**|  | 

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

