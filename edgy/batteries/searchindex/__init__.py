import edgy


class BaseSingletonHash(edgy.Model):
    id: int = edgy.BigIntegerField(primary_key=True, minimum=0, null=False)
    hash: str = edgy.CharField(max_length=255, unique=True, null=False)

    class Meta:
        abstract = True


class BaseKeyValue(edgy.Model):
    id: int = edgy.BigIntegerField(primary_key=True, minimum=0, null=False)
    # singleton: SingletonHash = edgy.ForeignKey(
    #     SingletonHash, on_delete=edgy.CASCADE, related_name="kvs", null=True
    # )
    ...
    kv_hash: str = edgy.CharField(max_length=255, null=True)
    kv: str = edgy.TextField(max_length=255)

    class Meta:
        abstract = True

    def __init_subclass__(cls, singleton_model="SingletonHash", **kwargs):
        if not hasattr(cls, "singleton"):
            cls.__annotations__["singleton"] = singleton_model
            cls.singleton = edgy.ForeignKey(
                singleton_model, on_delete=edgy.CASCADE, related_name="kvs", null=True
            )
        super().__init_subclass__(**kwargs)


# how to use
# class SingletonHash(BaseSingletonHash): pass
# class KeyValue(BaseKeyValue, singleton_model=SingletonHash): pass
# or
# class KeyValue(BaseKeyValue, singleton_model=SingletonHash):
#     singleton: SingletonHash = edgy.ForeignKey(
#         SingletonHash, on_delete=edgy.CASCADE, related_name="kvs", null=True
#     )
