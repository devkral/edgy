# Tips and tricks

This part is dedicated to some code organisation within your application.

The examples are more focused on the [Esmerald](https://esmerald.dymmond.com) as the author is the
same but again, you can do the same in your favourite framework.

## Placing your connection in a centralised place

This is probably what you would like to do in your application since you don't want to declare
over and over again the same variables.

The main reason for that is the fact that every time you declare a [registry](./registry.md) or a
`database`, in fact you are generating a new object and this is not great if you need to access
the models used with the main registry, right?

### Place the connection details inside a global settings file

This is probably the easiest way to place the connection details and particulary for Esmerald since
it comes with a simple and easy way of accesing the settings anywhere in the code.

Something simple like this:

```python hl_lines="18-25"
{!> ../docs_src/tips/settings.py !}
```

As you can see, now you have the `db_connection` in one place and easy to access from anywhere in
your code. In the case of Esmerald:

```python hl_lines="3"
from esmerald.conf import settings

database, registry = settings.db_connection
```

**But is this enough?**. No.

As mentioned before, when assigning or creating a variable, python itself generates a new object
with a different `id` which can differ from each time you need to import the settings into the
needed places.

We won't talk about this pythonic tricks as there are plenty of documentation on the web and better
suited for that same purpose.

How do we solve this issue? Enters [lru_cache](#the-lru-cache).

## The LRU cache

LRU extends for **least recently used**.

A very common technique that aims to help caching certain pieces of functionality within your
codebase and making sure you **do not generate** extra objects and this is exactly what we need.

Use the example above, let us now create a new file called `utils.py` where we will be applying
the `lru_cache` technique for our `db_connection`.

```python title="utils.py" hl_lines="6"
{!> ../docs_src/tips/lru.py !}
```

This will make sure that from now on you will always use the same connection and registry within
your appliction by importing the `get_db_connection()` anywhere is needed.

## Pratical example

Let us now assemble everything and generate an application that will have:

* **User model**
* **Ready to generate** [migrations](./migrations/migrations.md)
* **Starts the database connections**

For this example we will have the following structure (we won't be use using all of the files).
We won't be creating views as this is not the purpose of the example.

```shell
.
└── myproject
    ├── __init__.py
    ├── apps
    │   ├── __init__.py
    │   └── accounts
    │       ├── __init__.py
    │       ├── tests.py
    │       └── v1
    │           ├── __init__.py
    │           ├── schemas.py
    │           ├── urls.py
    │           └── views.py
    ├── configs
    │   ├── __init__.py
    │   ├── development
    │   │   ├── __init__.py
    │   │   └── settings.py
    │   ├── settings.py
    │   └── testing
    │       ├── __init__.py
    │       └── settings.py
    ├── main.py
    ├── serve.py
    ├── utils.py
    ├── tests
    │   ├── __init__.py
    │   └── test_app.py
    └── urls.py
```

This structure is generated by using the
[Esmerald directives](https://esmerald.dymmond.com/management/directives/)

### The settings

As mentioned before we will have a settings file with database connection properties assembled.

```python title="my_project/configs/settings.py" hl_lines="18-19"
{!> ../docs_src/tips/settings.py !}
```

### The utils

Now we create the `utils.py` where we appy the [LRU](#the-lru-cache) technique.

```python title="myproject/utils.py" hl_lines="6"
{!> ../docs_src/tips/lru.py !}
```

### The models

We can now start creating our [models](./models.md) and making sure we keep them always in the
same [registry](./registry.md)


```python title="myproject/apps/accounts/models.py" hl_lines="8 19"
{!> ../docs_src/tips/models.py !}
```

Here applied the [inheritance](./models.md#with-inheritance) to make it clean and more readable in
case we want even more models.

As you could also notice, we are importing the `get_db_connection()` previously created. This is
now what we will be using everywhere.

### Prepare the application to allow migrations

Now it is time to tell the application that your models and migrations are managed by Edgy.
More information on [migrations](./migrations/migrations.md) where explains how to use it.


```python title="myproject/main.py" hl_lines="9 12 32 38"
{!> ../docs_src/tips/migrations.py !}
```

This will make sure that your application migrations are now managed by **Edgy**.

### Hook the connection

As a final step we now need to make sure we hook the [connection](./connection.md) in our
application.

```python title="myproject/main.py" hl_lines="9 32 36-37"
{!> ../docs_src/tips/connection.py !}
```

And this is it.

## Notes

The above [example](#pratical-example) shows how you could take leverage of a centralised place
to manage your connections and then use it across your application keeping your code always clean
not redundant and beautiful.

This example is applied to any of your favourite frameworks and you can use as many and different
techniques as the ones you see fit for your own purposes.

**Edgy is framework agnostic**.