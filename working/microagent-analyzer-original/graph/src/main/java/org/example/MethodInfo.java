package org.example;

import java.util.ArrayList;
import java.util.List;

/**
 * Stores information about a method, including its signature and annotations
 */
public class MethodInfo {
    private String name;
    private String returnType;
    private List<String> parameterTypes = new ArrayList<>();
    private List<String> annotations = new ArrayList<>();
    private boolean isPublic;
    private boolean isPrivate;
    private boolean isProtected;
    private boolean isStatic;
    private boolean isAbstract;
    private boolean isFinal;
    
    public MethodInfo(String name, String returnType) {
        this.name = name;
        this.returnType = returnType;
    }
    
    public void addParameterType(String parameterType) {
        parameterTypes.add(parameterType);
    }
    
    public void addAnnotation(String annotation) {
        annotations.add(annotation);
    }
    
    public String getName() {
        return name;
    }
    
    public String getReturnType() {
        return returnType;
    }
    
    public List<String> getParameterTypes() {
        return parameterTypes;
    }
    
    public List<String> getAnnotations() {
        return annotations;
    }
    
    public boolean isPublic() {
        return isPublic;
    }
    
    public void setPublic(boolean isPublic) {
        this.isPublic = isPublic;
    }
    
    public boolean isPrivate() {
        return isPrivate;
    }
    
    public void setPrivate(boolean isPrivate) {
        this.isPrivate = isPrivate;
    }
    
    public boolean isProtected() {
        return isProtected;
    }
    
    public void setProtected(boolean isProtected) {
        this.isProtected = isProtected;
    }
    
    public boolean isStatic() {
        return isStatic;
    }
    
    public void setStatic(boolean isStatic) {
        this.isStatic = isStatic;
    }
    
    public boolean isAbstract() {
        return isAbstract;
    }
    
    public void setAbstract(boolean isAbstract) {
        this.isAbstract = isAbstract;
    }
    
    public boolean isFinal() {
        return isFinal;
    }
    
    public void setFinal(boolean isFinal) {
        this.isFinal = isFinal;
    }
    
    /**
     * Get a string representation of the method signature
     */
    public String getSignature() {
        StringBuilder sb = new StringBuilder();
        
        if (isPublic) {
            sb.append("public ");
        } else if (isPrivate) {
            sb.append("private ");
        } else if (isProtected) {
            sb.append("protected ");
        }
        
        if (isStatic) {
            sb.append("static ");
        }
        
        if (isFinal) {
            sb.append("final ");
        }
        
        if (isAbstract) {
            sb.append("abstract ");
        }
        
        sb.append(returnType).append(" ").append(name).append("(");
        
        for (int i = 0; i < parameterTypes.size(); i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(parameterTypes.get(i));
        }
        
        sb.append(")");
        
        return sb.toString();
    }
} 