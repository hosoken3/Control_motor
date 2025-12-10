```pythonGet-Process | Where-Object {$_.ProcessName -like "*python*"}
```

Handles  NPM(K)    PM(K)      WS(K)     CPU(s)     Id  SI ProcessName        
-------  ------    -----      -----     ------     --  -- -----------
    188      15     9052      20832       0.09  22720   3 python
     61       5      744       4172       0.00  35128   3 python


---

```python
Stop-Process -Id 22720 -Force
Stop-Process -Id 35128 -Force
```